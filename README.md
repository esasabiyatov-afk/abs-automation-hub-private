# Automation Hub

Универсальное локальное ядро для приложений автоматизации и генерации отчётов. Приложения могут быть написаны на любом языке: они подключаются к одному HTTP API, а специфическая логика добавляется небольшими Python-плагинами.

## Что уже есть

- единая SQLite-база с источниками, заданиями, запусками, версиями записей, файлами отчётов и журналом аудита;
- REST API на `127.0.0.1` с Bearer-токеном;
- защита от повторной загрузки одинаковых записей по SHA-256;
- подключаемые плагины без изменения ядра;
- пример импорта JSON и формирования CSV;
- транзакции, внешние ключи и WAL-режим SQLite.
- fail-closed политика интеграции: разрешены только чтение и явно подтверждённые маршруты скачивания;
- начальная обезличенная спецификация интерфейса Tolubay в `specs/tolubay-observed.json`.
- HTTP-адаптер Tolubay без Selenium и Chrome: авторизация, одиночный и пакетный поиск клиентов, чтение полной анкеты, активных и закрытых счетов, формирование и скачивание отчётов.
- обезличенный каталог 16 логических сценариев отчётов: 11 стандартных форм, отчёт по шаблону, 3 динамических дополнительных отчёта и кредитный отчёт по просрочке — в `specs/tolubay-report-forms.json`.

Сервис намеренно не хранит пароли от банковских систем. Секреты должны приходить из переменных окружения или отдельного защищённого хранилища.

## Отчет Tolubay по шаблону без браузера

Адаптер использует только стандартную библиотеку Python. Chrome, WebDriver и загрузка пакетов из интернета не нужны.

```powershell
cd outputs/automation-hub
$env:PYTHONPATH = "$PWD/src"
$env:TOLUBAY_LOGIN = "ваш-логин"
$env:TOLUBAY_PASSWORD = "ваш-пароль"

python -m automation_hub.tolubay_cli `
  --template "C:\Reports\template.xlsx" `
  --date "21.08.2026" `
  --output "C:\Reports\Ready"
```

Для рабочего развёртывания установите внутренний сертификат банка в хранилище доверенных сертификатов Windows либо передайте путь через `TOLUBAY_CA_FILE`. Параметр `--insecure` предназначен только для временной диагностики.

Использование из Python:

```python
from automation_hub.tolubay import TolubayClient, TolubayConfig

client = TolubayClient(TolubayConfig())
client.login(login, password)
result = client.generate_template_report(
    "template.xlsx",
    "21.08.2026",
    "ready-reports",
)
print(result.path)
```

Поиск, анкета и счета:

```python
customers = client.search_customers({"SearchIdentificationNo": "значение"})
batch = client.search_customers_batch([
    {"SearchCustomerID": "123"},
    {"SearchAccountNo": "счёт"},
])
questionnaire = client.get_customer_questionnaire(customers[0].customer_id)
active_accounts = client.get_accounts(customers[0].customer_id)
all_accounts = client.get_accounts(customers[0].customer_id, include_closed=True)
```

Обычная форма отчёта использует точный маршрут и поля из
`specs/tolubay-report-forms.json`:

```python
download = client.execute_report(
    "/OnlineBank.Management.MVC/BalanceGroupsStatementReport/Execute",
    {
        "Period.StartDate": "01.08.2026",
        "Period.EndDate": "20.08.2026",
        "Value": "XLSX",
    },
    "ready-reports",
)
```

Дополнительные отчёты:

```python
catalogue = client.list_additional_reports()
download = client.generate_additional_report(
    report_name=catalogue[0].report_name,
    report_type=catalogue[0].report_type,
    start_date="01.08.2026",
    end_date="20.08.2026",
    output_dir="ready-reports",
)
```

## Быстрый запуск

Требуется Python 3.11+.

```powershell
cd outputs/automation-hub
$env:PYTHONPATH = "$PWD/src"
$env:HUB_API_TOKEN = "замените-на-длинный-случайный-токен"
python -m automation_hub --root .hub --plugins plugins
```

Проверка:

```powershell
$headers = @{ Authorization = "Bearer $env:HUB_API_TOKEN" }
Invoke-RestMethod http://127.0.0.1:8765/health -Headers $headers
Invoke-RestMethod http://127.0.0.1:8765/plugins -Headers $headers
```

## Подключение первого приложения

1. Приложение отправляет данные через собственный плагин либо создаёт задание через API.
2. Ядро сохраняет нормализованные записи и историю запусков.
3. Плагин отчёта читает записи и создаёт XLSX, CSV, PDF или другой файл.
4. Приложение получает статус запуска через `/runs/{id}`.

Создание источника:

```powershell
$source = Invoke-RestMethod http://127.0.0.1:8765/sources `
  -Method Post -Headers $headers -ContentType application/json `
  -Body '{"name":"clients","kind":"json","config":{"path":"C:\\data\\clients.json"}}'
```

Создание и запуск задания:

```powershell
$body = @{
  name = "clients-import"
  plugin = "example.json_import"
  source_id = $source.id
  params = @{ id_field = "id" }
} | ConvertTo-Json -Depth 4

$task = Invoke-RestMethod http://127.0.0.1:8765/tasks `
  -Method Post -Headers $headers -ContentType application/json -Body $body

Invoke-RestMethod "http://127.0.0.1:8765/tasks/$($task.id)/run" `
  -Method Post -Headers $headers
```

## Контракт плагина

Каждый файл в `plugins/` экспортирует объект `plugin`:

```python
from automation_hub.plugins import PluginResult

class MyPlugin:
    name = "company.my_task"
    description = "Что делает плагин"

    def run(self, context, params):
        return PluginResult(
            records=[{"external_id": "123", "payload": {"value": 10}}],
            metrics={"processed": 1},
        )

plugin = MyPlugin()
```

Если плагин возвращает записи, у задания должен быть `source_id`. Для каждого элемента обязательны `external_id` и `payload`.

## API

| Метод | Маршрут | Назначение |
|---|---|---|
| GET | `/health` | Проверка сервиса |
| GET | `/plugins` | Список плагинов |
| GET/POST | `/sources` | Источники данных |
| GET/POST | `/tasks` | Задания |
| POST | `/tasks/{id}/run` | Синхронный запуск задания |
| GET | `/runs?limit=100` | История запусков |
| GET | `/runs/{id}` | Запуск и его артефакты |
| GET | `/records?source_id=1` | Версии записей источника |

## Следующие расширения

- PostgreSQL для многопользовательской установки;
- очередь фоновых заданий и расписание;
- роли и отдельные токены приложений;
- шифрование чувствительных полей;
- плагины XLSX/PDF и адаптер к конкретному банковскому интерфейсу;
- административная веб-панель.

Начинать интеграцию следует с одного отчёта и обезличенного набора данных. После стабилизации контракта остальные приложения подключаются как новые плагины.

## Статус адаптера Tolubay

Карта создана без сохранения клиентских данных. В клиенте реализованы 14 параметров поиска, пакетный поиск, чтение полной анкеты в режиме `isShow=True`, получение активных и закрытых счетов, три вида выписок через общий исполнитель, 11 стандартных форм раздела «Отчёты», кредитный отчёт по просрочке, дополнительные отчёты и отчёт по XLSX-шаблону. Сценарий шаблонного отчёта ранее проверен на реальном сайте полностью; остальные контракты подтверждены в интерфейсе и покрыты локальным HTTP-имитатором.

`ReadOnlyPolicy` блокирует другой домен, любые Delete/Close/Restore и все неизвестные POST-маршруты. Анкета читается только по точному GET-маршруту с обязательным `isShow=True`; её POST-форма никогда не отправляется. Разрешены только подтверждённые POST-запросы поиска данных, генерации отчётов и загрузки закрытых счетов.
