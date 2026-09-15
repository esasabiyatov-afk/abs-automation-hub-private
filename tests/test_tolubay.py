from __future__ import annotations

import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from automation_hub.tolubay import ProtocolError, TolubayClient, TolubayConfig


ROOT = "/OnlineBank.Management.MVC"


class _FakeTolubayHandler(BaseHTTPRequestHandler):
    requests: list[tuple[str, str, bytes]] = []

    def log_message(self, format: str, *args: object) -> None:
        return

    def _body(self) -> bytes:
        length = int(self.headers.get("Content-Length", "0"))
        return self.rfile.read(length)

    def _send(self, body: bytes, content_type: str = "text/html; charset=utf-8") -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload: dict[str, object]) -> None:
        self._send(json.dumps(payload).encode(), "application/json")

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        self.requests.append(("GET", self.path, b""))
        parsed = urlparse(self.path)
        if self.path == f"{ROOT}/Account/SignIn":
            self._send(
                b'<form method="post"><input name="__RequestVerificationToken" value="csrf"></form>'
            )
        elif self.path == f"{ROOT}/Customers/Search":
            self._send(b"<title>Search</title>")
        elif parsed.path == f"{ROOT}/Customers/Details":
            model = {
                "CustomerID": 42,
                "Deposits": [
                    {
                        "MainAccountNo": "1001",
                        "CurrencyID": 417,
                        "DepositAccountStatusID": 1,
                        "CloseDate": None,
                    }
                ],
            }
            self._send(f"<script>var vmDepositsJs = {json.dumps(model)};</script>".encode())
        elif parsed.path == f"{ROOT}/Customers/Edit":
            self.send_response(302)
            self.send_header(
                "Location",
                f"{ROOT}/Customers/EditPrivateCustomer?customerId=42&isShow=True",
            )
            self.end_headers()
        elif parsed.path == f"{ROOT}/Customers/EditPrivateCustomer":
            self._send(
                b'<form method="post" action="/OnlineBank.Management.MVC/Customers/EditPrivateCustomer">'
                b'<input type="hidden" name="CustomerId" value="42">'
                b'<input name="GeneralInfoModel.Surname" value="Example">'
                b'<select name="GeneralInfoModel.NationalityId">'
                b'<option value="1" selected>Country</option></select></form>'
            )
        elif parsed.path == f"{ROOT}/Management/AdditionalReport":
            model = {
                "Filter": {
                    "ReportName": {"PropertyName": "ReportName", "Value": None}
                },
                "ReferenceType": "AdditionalReportItem",
                "Context": None,
                "DescriptorType": None,
                "Pagination": {"Page": 1, "PageSize": 20, "TotalItems": 0},
            }
            self._send(f"<script>var vmUniReferenceJs = {json.dumps(model)};</script>".encode())
        elif self.path == f"{ROOT}/Job":
            model = {
                "Filter": {"UserID": {"PropertyName": "UserID", "Value": "1"}},
                "ReferenceType": "JobType",
                "Context": [{"PropertyName": "UserID", "Value": "1"}],
                "DescriptorType": None,
                "Pagination": {"Page": 1, "PageSize": 20, "TotalItems": 0},
            }
            self._send(f"<script>var vmUniReferenceJs = {json.dumps(model)};</script>".encode())
        elif self.path == f"{ROOT}/Job/Download?id=77":
            body = b"PK\x03\x04fake-xlsx"
            self.send_response(200)
            self.send_header(
                "Content-Type",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
            self.send_header("Content-Disposition", 'attachment; filename="result.xlsx"')
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == f"{ROOT}/Job/Download?id=78":
            body = b"PK\x03\x04additional-xlsx"
            self.send_response(200)
            self.send_header(
                "Content-Type",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
            self.send_header("Content-Disposition", 'attachment; filename="additional.xlsx"')
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif parsed.path == f"{ROOT}/BalanceGroupsStatementReport/Report":
            body = b"\xd0\xcf\x11\xe0fake-xls"
            self.send_response(200)
            self.send_header("Content-Type", "application/vnd.ms-excel")
            self.send_header("Content-Disposition", 'attachment; filename="statement.xls"')
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_error(404)

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        body = self._body()
        self.requests.append(("POST", self.path, body))
        if self.path == f"{ROOT}/Account/SignIn":
            fields = parse_qs(body.decode())
            if fields.get("UserName") != ["user"] or fields.get("Password") != ["pass"]:
                self.send_error(403)
                return
            self.send_response(302)
            self.send_header("Location", f"{ROOT}/Customers/Search")
            self.send_header("Set-Cookie", "site=session; Path=/")
            self.end_headers()
        elif self.path == f"{ROOT}/Customers/SearchResult":
            fields = parse_qs(body.decode())
            if fields.get("ShowLinks") != ["True"] or fields.get("SearchCustomerID") != ["42"]:
                self.send_error(400)
                return
            if self.headers.get("X-Requested-With") != "XMLHttpRequest":
                self.send_error(400)
                return
            self._send(
                """
                <table><thead><tr><th>ID</th><th>ФИО / Наименование</th>
                <th>Паспорт / ИНН</th><th>Дата рождения</th>
                <th>Фактический адрес</th><th>Номера телефонов</th><th></th></tr></thead>
                <tbody><tr><td>Клиент № 42</td><td>Тестовый клиент</td><td>ID-1</td>
                <td>01.01.2000</td><td>Адрес</td><td>000</td><td>
                <a href="/OnlineBank.Management.MVC/Customers/Details?customerID=42">view</a>
                <a href="/OnlineBank.Management.MVC/Customers/Edit?customerID=42&amp;isShow=True">form</a>
                </td></tr></tbody></table>
                """.encode("utf-8")
            )
        elif self.path == f"{ROOT}/Management/ExcelTemplatesReportJob":
            context = {
                "FileData": "redacted",
                "FileName": "template.xlsx",
                "ReportDate": "2026-08-21T00:00:00",
                "OrganizationName": "ORG",
                "BranchID": 1,
                "IncludeFormulaAsComment": False,
                "UseCache": False,
                "ContextKey": "ctx-1",
                "ContextGuid": "guid-1",
                "UserID": 1,
                "JobName": None,
            }
            model = {
                "Context": context,
                "Data": {},
                "ContextDataType": "ContextType",
                "DataType": "DataType",
            }
            self._send(f"<script>var vmJobJs = {json.dumps(model)};</script>".encode())
        elif self.path == f"{ROOT}/Management/AdditionalReportJob":
            context = {"ContextKey": "ctx-add", "ContextGuid": "guid-add", "UserID": 1}
            model = {
                "Context": context,
                "Data": {},
                "ContextDataType": "AdditionalContextType",
                "DataType": "AdditionalDataType",
            }
            self._send(f"<script>var vmJobJs = {json.dumps(model)};</script>".encode())
        elif self.path in {
            f"{ROOT}/Management/ExcelTemplatesReportJob/CheckService",
            f"{ROOT}/Management/ExcelTemplatesReportJob/Run",
            f"{ROOT}/Management/AdditionalReportJob/CheckService",
            f"{ROOT}/Management/AdditionalReportJob/Run",
        }:
            self._json({"status": "ok", "message": "accepted"})
        elif self.path == f"{ROOT}/Job/Load":
            payload = json.loads(body)
            if not isinstance(payload.get("Filter"), list):
                self.send_error(400)
                return
            self._json(
                {
                    "data": {
                        "Items": [
                            {
                                "ID": 9,
                                "ContextKey": "ctx-1",
                                "JobState": 1,
                                "Result": "completed with accepted formula messages",
                                "JobResults": [{"ID": 77, "Name": "result.xlsx"}],
                            },
                            {
                                "ID": 10,
                                "ContextKey": "ctx-add",
                                "JobState": 1,
                                "Result": "",
                                "JobResults": [{"ID": 78, "Name": "additional.xlsx"}],
                            }
                        ],
                        "Pagination": {"Page": 1, "PageSize": 20, "TotalItems": 1},
                    }
                }
            )
        elif self.path == f"{ROOT}/Management/AdditionalReport/Load":
            self._json(
                {
                    "data": {
                        "Items": [
                            {
                                "ReportName": "Additional one",
                                "ReportType": "Type.One",
                                "ReportGroup": "General",
                            }
                        ],
                        "Pagination": {"Page": 1, "PageSize": 20, "TotalItems": 1},
                    }
                }
            )
        elif self.path == f"{ROOT}/Deposits/Customer/GetDepositsByCustomerId":
            payload = json.loads(body)
            if payload != {"customerId": 42, "showAll": False}:
                self.send_error(400)
                return
            self._json(
                {
                    "data": {
                        "CustomerID": 42,
                        "Deposits": [
                            {
                                "MainAccountNo": "1001",
                                "CurrencyID": 417,
                                "DepositAccountStatusID": 1,
                                "CloseDate": None,
                            },
                            {
                                "MainAccountNo": "1002",
                                "CurrencyID": 840,
                                "DepositAccountStatusID": 5,
                                "CloseDate": "2025-01-01",
                            },
                        ],
                    }
                }
            )
        elif self.path == f"{ROOT}/BalanceGroupsStatementReport/Execute":
            self._send(
                b'<a href="/OnlineBank.Management.MVC/BalanceGroupsStatementReport/Report?reportID=8">download</a>'
            )
        else:
            self.send_error(404)


class TolubayClientTests(unittest.TestCase):
    def setUp(self) -> None:
        _FakeTolubayHandler.requests = []
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeTolubayHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temp.cleanup()

    def test_template_report_full_http_flow(self) -> None:
        template = self.root / "template.xlsx"
        template.write_bytes(b"PK\x03\x04template")
        output = self.root / "reports"
        base_url = f"http://127.0.0.1:{self.server.server_port}"
        client = TolubayClient(
            TolubayConfig(base_url=base_url, poll_interval_seconds=0.0),
            sleeper=lambda _: None,
        )

        client.login("user", "pass")
        result = client.generate_template_report(template, "21.08.2026", output)

        self.assertEqual(result.job_id, 9)
        self.assertEqual(result.result_id, 77)
        self.assertEqual(result.file_name, "result.xlsx")
        self.assertEqual(result.path.read_bytes(), b"PK\x03\x04fake-xlsx")
        self.assertTrue(result.completed_with_messages)

        paths = [(method, path) for method, path, _ in _FakeTolubayHandler.requests]
        self.assertIn(("POST", f"{ROOT}/Management/ExcelTemplatesReportJob/Run"), paths)
        self.assertIn(("POST", f"{ROOT}/Job/Load"), paths)
        self.assertIn(("GET", f"{ROOT}/Job/Download?id=77"), paths)

    def test_stop_route_remains_blocked(self) -> None:
        base_url = f"http://127.0.0.1:{self.server.server_port}"
        client = TolubayClient(TolubayConfig(base_url=base_url))
        with self.assertRaises(PermissionError):
            client._request("POST", f"{ROOT}/Management/ExcelTemplatesReportJob/Stop")

    def _logged_in_client(self) -> TolubayClient:
        client = TolubayClient(
            TolubayConfig(base_url=f"http://127.0.0.1:{self.server.server_port}")
        )
        client.login("user", "pass")
        return client

    def test_search_questionnaire_and_accounts_are_read_only(self) -> None:
        client = self._logged_in_client()
        customers = client.search_customers({"SearchCustomerID": "42"})
        self.assertEqual(len(customers), 1)
        self.assertEqual(customers[0].customer_id, "42")
        self.assertIn("Customers/Details", customers[0].details_url or "")

        questionnaire = client.get_customer_questionnaire("42")
        self.assertEqual(questionnaire.customer_type, "Private")
        self.assertEqual(questionnaire.fields["GeneralInfoModel.Surname"], "Example")
        self.assertEqual(
            questionnaire.fields["GeneralInfoModel.NationalityId"],
            {"value": "1", "text": "Country"},
        )

        active = client.get_accounts(42)
        all_accounts = client.get_accounts(42, include_closed=True)
        self.assertEqual([item.account_no for item in active], ["1001"])
        self.assertEqual([item.account_no for item in all_accounts], ["1001", "1002"])
        self.assertFalse(all_accounts[0].is_closed)
        self.assertTrue(all_accounts[1].is_closed)

        methods = [method for method, _, _ in _FakeTolubayHandler.requests]
        self.assertNotIn("DELETE", methods)
        self.assertFalse(
            any(path.startswith(f"{ROOT}/Customers/EditPrivateCustomer") and method == "POST"
                for method, path, _ in _FakeTolubayHandler.requests)
        )

    def test_lookup_only_profile_blocks_report_jobs_but_allows_lookup_reads(self) -> None:
        client = TolubayClient(
            TolubayConfig(
                base_url=f"http://127.0.0.1:{self.server.server_port}",
                lookup_only=True,
            )
        )
        client.login("user", "pass")

        customers = client.search_customers({"SearchCustomerID": "42"})
        client.get_customer_questionnaire(customers[0].customer_id)
        client.get_accounts(customers[0].customer_id, include_closed=True)

        with self.assertRaises(PermissionError):
            client._request("POST", f"{ROOT}/Management/ExcelTemplatesReportJob/Run")

    def test_unexpected_search_page_is_error_not_not_found(self) -> None:
        client = self._logged_in_client()
        client._post_form = lambda *args, **kwargs: (
            b"<html><h1>Temporary ABS error</h1></html>",
            None,
            f"http://127.0.0.1:{self.server.server_port}{ROOT}/Customers/SearchResult",
        )
        with self.assertRaisesRegex(ProtocolError, "нельзя определить"):
            client.search_customers({"SearchIdentificationNo": "99999999999999"})

    def test_official_empty_search_marker_means_not_found(self) -> None:
        client = self._logged_in_client()
        client._post_form = lambda *args, **kwargs: (
            "<script>bootstrapAlert('', 'Клиенты с заданными параметрами не найдены');</script>".encode(),
            None,
            f"http://127.0.0.1:{self.server.server_port}{ROOT}/Customers/SearchResult",
        )
        self.assertEqual(
            client.search_customers({"SearchIdentificationNo": "99999999999999"}),
            [],
        )

    def test_catalogued_report_execute_and_download(self) -> None:
        client = self._logged_in_client()
        result = client.execute_report(
            f"{ROOT}/BalanceGroupsStatementReport/Execute",
            {"Period.StartDate": "01.01.2026", "Period.EndDate": "02.01.2026"},
            self.root / "reports",
        )
        self.assertEqual(result.file_name, "statement.xls")
        self.assertTrue(result.path.read_bytes().startswith(b"\xd0\xcf\x11\xe0"))

    def test_additional_report_catalogue_and_job_download(self) -> None:
        client = self._logged_in_client()
        catalogue = client.list_additional_reports()
        self.assertEqual(len(catalogue), 1)
        self.assertEqual(catalogue[0].report_type, "Type.One")
        result = client.generate_additional_report(
            report_name=catalogue[0].report_name,
            report_type=catalogue[0].report_type,
            start_date="01.01.2026",
            end_date="02.01.2026",
            output_dir=self.root / "additional",
        )
        self.assertEqual(result.file_name, "additional.xlsx")
        self.assertTrue(result.path.read_bytes().startswith(b"PK\x03\x04"))

    def test_unlisted_report_and_non_view_edit_are_blocked(self) -> None:
        client = self._logged_in_client()
        with self.assertRaises(PermissionError):
            client.execute_report(f"{ROOT}/Customers/Save", {}, self.root)
        with self.assertRaises(PermissionError):
            client._request("GET", f"{ROOT}/Customers/Edit?customerID=42")


if __name__ == "__main__":
    unittest.main()
