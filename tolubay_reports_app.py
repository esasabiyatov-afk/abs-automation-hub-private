from __future__ import annotations

import argparse
import json
import sys
import threading
import webbrowser
from dataclasses import asdict, dataclass
from datetime import date
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

SCRIPT_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
SOURCE_DIR = SCRIPT_DIR / "src"
if SOURCE_DIR.is_dir() and str(SOURCE_DIR) not in sys.path:
    sys.path.insert(0, str(SOURCE_DIR))

from automation_hub.tolubay import AdditionalReportItem, TolubayClient, TolubayConfig  # noqa: E402
from automation_hub.memorial_order_xls import process_memorial_order_xls  # noqa: E402


MEMORIAL_ORDER_REPORT = "Сводный мемориальный ордер"


@dataclass(frozen=True)
class ReportTask:
    kind: str
    title: str
    values: dict[str, Any]


def today_text() -> str:
    return date.today().strftime("%d.%m.%Y")


def form_defaults(fields: list[dict[str, Any]]) -> dict[str, str]:
    """Produce editable defaults from the observed ABS form schema."""
    values: dict[str, str] = {}
    for field in fields:
        if field.get("disabled") or not (name := field.get("name")):
            continue
        field_type = field.get("type", "text")
        if field_type == "radio":
            if field.get("checked"):
                values[name] = str(field.get("value", ""))
        elif field_type == "checkbox":
            values[name] = str(field.get("value", "true")) if field.get("checked") else "false"
        elif field_type == "select-one":
            options = field.get("options") or []
            if options:
                values[name] = str(options[0].get("value", ""))
        elif field_type == "hidden":
            values.setdefault(name, str(field.get("value", "")))
        else:
            values[name] = today_text() if "Date" in name else str(field.get("value", ""))
    return values


def load_report_forms(path: Path) -> dict[str, dict[str, Any]]:
    spec = json.loads(path.read_text(encoding="utf-8"))
    reports = [*spec.get("main_reports", []), *spec.get("loans_reports", [])]
    result: dict[str, dict[str, Any]] = {}
    for report in reports:
        forms = report.get("forms") or []
        if forms and forms[0].get("action"):
            result[str(report.get("label") or report.get("heading"))] = report
    if not result:
        raise ValueError("В спецификации не найдены формы отчётов")
    return result


def memorial_order_fields(
    report: dict[str, Any],
    *,
    branch_id: str,
    office_id: str,
    user_id: str,
    report_date: str,
) -> dict[str, str]:
    """Build the exact read-only fields for one employee's memorial order."""
    if not all(value.strip() for value in (branch_id, office_id, user_id, report_date)):
        raise ValueError("Для мемориального ордера заполните филиал, отделение, сотрудника и дату")
    fields = form_defaults(report["forms"][0]["fields"])
    fields.update(
        {
            "Branch.All": "False",
            "Branch.Value": branch_id.strip(),
            "Office.All": "False",
            "Office.Value": office_id.strip(),
            "User.All": "False",
            "User.Value": user_id.strip(),
            "Currency.All": "True",
            "OfficeUsersOperations.Value": "False",
            "IncludeFinalTurnovers.Value": "false",
            "ReportDate.Date": report_date.strip(),
            "Value": "XLS",
        }
    )
    return fields


def report_select_options(report: dict[str, Any], field_name: str) -> list[dict[str, str]]:
    """Return non-sensitive name/code pairs captured for an ABS select field."""
    fields = report["forms"][0]["fields"]
    for field in fields:
        if field.get("name") == field_name and field.get("type") == "select-one":
            return [
                {"value": str(option["value"]), "label": str(option["text"])}
                for option in field.get("options") or []
            ]
    return []


class ReportService:
    def __init__(self, *, insecure: bool) -> None:
        self.insecure = insecure
        self.forms = load_report_forms(SCRIPT_DIR / "specs" / "tolubay-report-forms.json")
        self.client: TolubayClient | None = None
        self.tasks: list[ReportTask] = []
        self.additional: list[AdditionalReportItem] = []
        self.lock = threading.RLock()

    def connect(self, login: str, password: str) -> None:
        if not login.strip() or not password:
            raise ValueError("Введите логин и пароль")
        client = TolubayClient(TolubayConfig(verify_tls=not self.insecure))
        client.login(login.strip(), password)
        with self.lock:
            self.client = client

    def require_client(self) -> TolubayClient:
        with self.lock:
            if self.client is None:
                raise ValueError("Сначала подключитесь к ABS")
            return self.client

    def queue(self) -> list[dict[str, Any]]:
        with self.lock:
            return [{"index": index, **asdict(task)} for index, task in enumerate(self.tasks)]

    def add(self, kind: str, values: dict[str, Any]) -> None:
        if kind == "statement":
            required = ("customer_id", "account_no", "currency_id", "start_date", "end_date")
            if not all(str(values.get(key, "")).strip() for key in required):
                raise ValueError("Для выписки заполните ID клиента, счёт, валюту и период")
            title = f"Выписка: {values['account_no']} ({values['start_date']} — {values['end_date']})"
        elif kind == "standard":
            report_name = str(values.get("report_name", ""))
            if report_name not in self.forms or not isinstance(values.get("fields"), dict):
                raise ValueError("Некорректный стандартный отчёт или параметры")
            title = f"Отчёт: {report_name}"
        elif kind == "memorial_order":
            if MEMORIAL_ORDER_REPORT not in self.forms:
                raise ValueError("В спецификации не найден Сводный мемориальный ордер")
            branch_id = str(values.get("branch_id", "")).strip()
            office_id = str(values.get("office_id", "")).strip()
            report_date = str(values.get("report_date", "")).strip()
            users = values.get("users")
            if not isinstance(users, list) or not users:
                raise ValueError("Добавьте хотя бы одного сотрудника")
            tasks: list[ReportTask] = []
            report = self.forms[MEMORIAL_ORDER_REPORT]
            for user in users:
                if not isinstance(user, dict):
                    raise ValueError("Некорректные данные сотрудника")
                user_id = str(user.get("id", "")).strip()
                user_name = str(user.get("name", "")).strip() or user_id
                fields = memorial_order_fields(
                    report,
                    branch_id=branch_id,
                    office_id=office_id,
                    user_id=user_id,
                    report_date=report_date,
                )
                tasks.append(
                    ReportTask(
                        "memorial_order",
                        f"Мемориальный ордер: {user_name} ({report_date})",
                        {
                            "fields": fields,
                            "user_name": user_name,
                            "print_after_processing": bool(values.get("print_after_processing")),
                        },
                    )
                )
            with self.lock:
                self.tasks.extend(tasks)
            return
        elif kind == "template":
            if not Path(str(values.get("path", ""))).is_file() or not str(values.get("date", "")).strip():
                raise ValueError("Выберите существующий XLSX-шаблон и укажите дату")
            title = f"Шаблон: {Path(str(values['path'])).name}"
        elif kind == "additional":
            if not all(str(values.get(key, "")).strip() for key in ("name", "type", "start", "end")):
                raise ValueError("Выберите дополнительный отчёт и период")
            title = f"Доп. отчёт: {values['name']}"
        else:
            raise ValueError("Неизвестный вид задания")
        with self.lock:
            self.tasks.append(ReportTask(kind, title, values))

    def move(self, index: int, direction: int) -> None:
        with self.lock:
            target = index + direction
            if not 0 <= index < len(self.tasks) or not 0 <= target < len(self.tasks):
                raise ValueError("Нельзя изменить порядок выбранного задания")
            self.tasks[index], self.tasks[target] = self.tasks[target], self.tasks[index]

    def remove(self, index: int) -> None:
        with self.lock:
            if not 0 <= index < len(self.tasks):
                raise ValueError("Задание не найдено")
            del self.tasks[index]

    def load_additional(self) -> list[dict[str, str]]:
        items = self.require_client().list_additional_reports()
        with self.lock:
            self.additional = items
        return [{"name": item.report_name, "type": item.report_type, "group": item.report_group} for item in items]

    def download(self, output_dir: str) -> list[str]:
        if not output_dir.strip():
            raise ValueError("Выберите папку для отчётов")
        output = Path(output_dir).expanduser()
        client = self.require_client()
        with self.lock:
            tasks = list(self.tasks)
        if not tasks:
            raise ValueError("Очередь пуста")
        saved: list[str] = []
        for task in tasks:
            if task.kind == "statement":
                result = client.generate_main_account_statement(output_dir=output, **task.values)
            elif task.kind == "standard":
                report = self.forms[task.values["report_name"]]
                result = client.execute_report(
                    report["forms"][0]["action"],
                    task.values["fields"],
                    output,
                    fallback_name=task.values["report_name"],
                )
            elif task.kind == "memorial_order":
                result = client.execute_report(
                    self.forms[MEMORIAL_ORDER_REPORT]["forms"][0]["action"],
                    task.values["fields"],
                    output,
                    fallback_name=f"memorial-order-{task.values['user_name']}",
                )
                process_memorial_order_xls(
                    result.path,
                    print_after_processing=bool(task.values["print_after_processing"]),
                )
            elif task.kind == "template":
                result = client.generate_template_report(
                    task.values["path"],
                    task.values["date"],
                    output,
                    use_cache=bool(task.values.get("cache")),
                    include_formula_as_comment=bool(task.values.get("formula")),
                )
            else:
                result = client.generate_additional_report(
                    report_name=task.values["name"],
                    report_type=task.values["type"],
                    start_date=task.values["start"],
                    end_date=task.values["end"],
                    output_dir=output,
                )
            saved.append(str(result.path))
        return saved


PAGE = r"""<!doctype html><html lang="ru"><meta charset="utf-8">
<title>Tolubay — отчёты</title>
<style>
body{font:14px Segoe UI,Arial,sans-serif;margin:22px;max-width:1080px;color:#17212b}h1{margin-top:0}
section{border:1px solid #d6dce5;border-radius:8px;padding:15px;margin:12px 0}label{display:block;margin:7px 0}
input,select,textarea,button{font:inherit;padding:6px}input,select,textarea{width:100%;box-sizing:border-box}textarea{height:175px;font-family:Consolas,monospace}
.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:0 16px}.row{display:flex;gap:8px;align-items:center}.row>*{width:auto}.note{color:#56616f}.ok{color:#187342}.error{color:#b42318}ol{padding-left:28px}li{margin:6px 0}
</style><body><h1>Tolubay: отчёты и очередь печати</h1>
<p class="note">Только получение и скачивание. Очередь не сохраняется, изменение данных ABS недоступно.</p>
<section><h2>Подключение</h2><div class="grid"><label>Логин<input id="login"></label><label>Пароль<input id="password" type="password"></label></div>
<label>Папка для скачанных отчётов<input id="output" value="ready-reports"></label><button onclick="connect()">Подключиться</button> <span id="status"></span></section>
<section><h2>Выписка по счёту</h2><div class="grid">
<label>ID клиента<input id="customer_id"></label><label>Номер счёта<input id="account_no"></label>
<label>Код валюты<input id="currency_id" value="417"></label><label>Валюта<input id="currency_name" value="KGS"></label>
<label>Дата с<input id="statement_start"></label><label>Дата по<input id="statement_end"></label>
<label>Формат<select id="statement_format"><option>PDF</option><option>XLS</option></select></label></div>
<button onclick="addStatement()">Добавить в очередь</button></section>
<section><h2>Стандартный отчёт</h2><label>Вид отчёта<select id="standard" onchange="setDefaults()"></select></label>
<label>Параметры JSON (предзаполнены по форме ABS; их можно отредактировать)<textarea id="fields"></textarea></label>
<button onclick="addStandard()">Добавить в очередь</button></section>
<section><h2>Документ дня: сводный мемориальный ордер</h2><p class="note">Для каждого сотрудника будет сформирован отдельный XLS-файл.</p><div class="grid">
<label>Филиал<select id="memorial_branch"></select></label><label>Отделение<select id="memorial_office"></select></label>
<label>Дата<input id="memorial_date"></label></div><label>Сотрудники: одна строка на человека в виде <code>код ABS | имя для очереди</code><textarea id="memorial_users" placeholder="123 | Иванова А.А."></textarea></label><label><input type="checkbox" id="memorial_print"> Печатать после обработки на принтере Windows по умолчанию</label><button onclick="addMemorialOrder()">Добавить сотрудников в очередь</button></section>
<section><h2>Отчёт по XLSX-шаблону</h2><div class="grid"><label>Путь к XLSX-шаблону<input id="template_path"></label><label>Дата отчёта<input id="template_date"></label></div>
<label><input type="checkbox" id="template_cache"> Использовать кэш ABS</label><label><input type="checkbox" id="template_formula"> Формулы как комментарии</label><button onclick="addTemplate()">Добавить в очередь</button></section>
<section><h2>Дополнительный отчёт</h2><button onclick="loadAdditional()">Загрузить каталог ABS</button><label>Отчёт<select id="additional"></select></label>
<div class="grid"><label>Дата с<input id="additional_start"></label><label>Дата по<input id="additional_end"></label></div><button onclick="addAdditional()">Добавить в очередь</button></section>
<section><h2>Очередь / порядок ручной печати</h2><p class="note">Сверху вниз — порядок подготовки к печати. Приложение не отправляет файлы на принтер автоматически.</p>
<ol id="queue"></ol><div class="row"><button onclick="download()">Скачать по порядку</button></div><p id="result"></p></section>
<script>
let forms={}, additional=[];
const today=()=>new Date().toLocaleDateString('ru-RU');
for(const id of ['statement_start','statement_end','template_date','additional_start','additional_end','memorial_date'])document.getElementById(id).value=today();
async function api(path,data={}){let r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});let x=await r.json();if(!r.ok)throw Error(x.error||'Ошибка');return x}
function msg(t,c='ok'){let e=document.getElementById('status');e.className=c;e.textContent=t}
function v(id){return document.getElementById(id).value.trim()}
function setDefaults(){document.getElementById('fields').value=JSON.stringify(forms[v('standard')].defaults,null,2)}
function setOptions(id,options){let s=document.getElementById(id);s.innerHTML='';options.forEach(o=>s.add(new Option(o.label,o.value)))}
function render(q){let e=document.getElementById('queue');e.innerHTML='';q.forEach(t=>{let li=document.createElement('li');li.textContent=t.title+' ';for(const [s,d] of [['↑',-1],['↓',1],['Убрать',0]]){let b=document.createElement('button');b.textContent=s;b.onclick=async()=>{try{await api(d?'/api/move':'/api/remove',{index:t.index,direction:d});refresh()}catch(e){msg(e.message,'error')}};li.append(b)}e.append(li)})}
async function refresh(){let x=await api('/api/queue');render(x.queue)}
async function connect(){try{msg('Подключение…');await api('/api/connect',{login:v('login'),password:document.getElementById('password').value});document.getElementById('password').value='';msg('Подключено')}catch(e){msg(e.message,'error')}}
async function add(kind,values){try{await api('/api/add',{kind,values});refresh()}catch(e){msg(e.message,'error')}}
function addStatement(){add('statement',{customer_id:v('customer_id'),account_no:v('account_no'),currency_id:v('currency_id'),currency_name:v('currency_name'),start_date:v('statement_start'),end_date:v('statement_end'),output_format:v('statement_format')})}
function addStandard(){try{add('standard',{report_name:v('standard'),fields:JSON.parse(document.getElementById('fields').value)})}catch(e){msg('Некорректный JSON','error')}}
function addMemorialOrder(){let users=v('memorial_users').split(/\r?\n/).map(line=>line.trim()).filter(Boolean).map(line=>{let [id,...name]=line.split('|');return {id:id.trim(),name:name.join('|').trim()}});add('memorial_order',{branch_id:v('memorial_branch'),office_id:v('memorial_office'),report_date:v('memorial_date'),users,print_after_processing:document.getElementById('memorial_print').checked})}
function addTemplate(){add('template',{path:v('template_path'),date:v('template_date'),cache:document.getElementById('template_cache').checked,formula:document.getElementById('template_formula').checked})}
async function loadAdditional(){try{let x=await api('/api/additional');additional=x.items;let s=document.getElementById('additional');s.innerHTML='';additional.forEach((a,i)=>s.add(new Option((a.group? a.group+': ':'')+a.name,i)));msg('Каталог загружен')}catch(e){msg(e.message,'error')}}
function addAdditional(){let a=additional[+v('additional')];if(!a){msg('Сначала загрузите каталог','error');return}add('additional',{name:a.name,type:a.type,start:v('additional_start'),end:v('additional_end')})}
async function download(){try{msg('Скачивание…');let x=await api('/api/download',{output_dir:v('output')});document.getElementById('result').textContent='Скачано файлов: '+x.paths.length;msg('Готово')}catch(e){msg(e.message,'error')}}
(async()=>{let x=await api('/api/forms');forms=x.forms;let s=document.getElementById('standard');Object.keys(forms).forEach(n=>s.add(new Option(n,n)));setOptions('memorial_branch',x.memorial.branch_options);setOptions('memorial_office',x.memorial.office_options);setDefaults();refresh()})()
</script></body></html>"""


def make_handler(service: ReportService) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def _json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _body(self) -> dict[str, Any]:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 <= size <= 1_000_000:
                raise ValueError("Некорректный размер запроса")
            value = json.loads(self.rfile.read(size).decode("utf-8"))
            if not isinstance(value, dict):
                raise ValueError("Ожидается JSON-объект")
            return value

        def do_GET(self) -> None:  # noqa: N802
            if urlparse(self.path).path == "/":
                body = PAGE.encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_error(HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:  # noqa: N802
            try:
                path = urlparse(self.path).path
                data = self._body()
                if path == "/api/forms":
                    memorial = service.forms[MEMORIAL_ORDER_REPORT]
                    payload = {
                        "forms": {name: {"defaults": form_defaults(report["forms"][0]["fields"])} for name, report in service.forms.items()},
                        "memorial": {
                            "branch_options": report_select_options(memorial, "Branch.Value"),
                            "office_options": report_select_options(memorial, "Office.Value"),
                        },
                    }
                elif path == "/api/connect":
                    service.connect(str(data.get("login", "")), str(data.get("password", "")))
                    payload = {"ok": True}
                elif path == "/api/queue":
                    payload = {"queue": service.queue()}
                elif path == "/api/add":
                    service.add(str(data.get("kind", "")), data.get("values", {}))
                    payload = {"queue": service.queue()}
                elif path == "/api/move":
                    service.move(int(data["index"]), int(data["direction"]))
                    payload = {"queue": service.queue()}
                elif path == "/api/remove":
                    service.remove(int(data["index"]))
                    payload = {"queue": service.queue()}
                elif path == "/api/additional":
                    payload = {"items": service.load_additional()}
                elif path == "/api/download":
                    payload = {"paths": service.download(str(data.get("output_dir", "")))}
                else:
                    self._json(HTTPStatus.NOT_FOUND, {"error": "Маршрут не найден"})
                    return
                self._json(HTTPStatus.OK, payload)
            except Exception as exc:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})

        def log_message(self, format: str, *args: Any) -> None:
            return

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description="Tolubay: скачивание отчётов и очередь печати")
    parser.add_argument("--insecure", action="store_true", help="Совместимый TLS-режим ABS")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(ReportService(insecure=args.insecure)))
    url = f"http://127.0.0.1:{args.port}/"
    print(f"Откройте {url}; для остановки нажмите Ctrl+C")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

