from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from automation_hub.tolubay import ReportDownloadResult
from tolubay_reports_app import (
    MEMORIAL_ORDER_REPORT,
    ReportService,
    form_defaults,
    memorial_order_fields,
    report_select_options,
)


class ReportAppTests(unittest.TestCase):
    def test_form_defaults_uses_checked_choices_and_dates(self) -> None:
        values = form_defaults(
            [
                {"name": "Value", "type": "radio", "value": "PDF", "checked": True},
                {"name": "Value", "type": "radio", "value": "XLS", "checked": False},
                {"name": "Branch.Value", "type": "select-one", "options": [{"value": "5"}]},
                {"name": "Period.StartDate", "type": "text"},
                {"name": "disabled", "type": "text", "disabled": True},
            ]
        )
        self.assertEqual(values["Value"], "PDF")
        self.assertEqual(values["Branch.Value"], "5")
        self.assertRegex(values["Period.StartDate"], r"^\d{2}\.\d{2}\.\d{4}$")
        self.assertNotIn("disabled", values)

    def test_memorial_order_fields_select_all_users_and_xls(self) -> None:
        report = {
            "forms": [
                {"fields": [
                    {"name": "Branch.All", "type": "radio", "value": "False", "checked": True},
                    {"name": "Office.All", "type": "radio", "value": "False", "checked": True},
                    {"name": "User.All", "type": "radio", "value": "False", "checked": True},
                    {"name": "Value", "type": "radio", "value": "PDF", "checked": True},
                ]}
            ]
        }
        fields = memorial_order_fields(
            report,
            branch_id="1022",
            office_id="1057",
            report_date="15.09.2026",
        )
        self.assertEqual(fields["Branch.All"], "False")
        self.assertEqual(fields["Branch.Value"], "1022")
        self.assertEqual(fields["Office.All"], "False")
        self.assertEqual(fields["Office.Value"], "1057")
        self.assertEqual(fields["User.All"], "True")
        self.assertNotIn("User.Value", fields)
        self.assertEqual(fields["Value"], "XLS")

    def test_report_select_options_returns_display_names_and_codes(self) -> None:
        report = {"forms": [{"fields": [{"name": "Branch.Value", "type": "select-one", "options": [{"value": "1022", "text": "Филиал"}]}]}]}
        self.assertEqual(
            report_select_options(report, "Branch.Value"),
            [{"value": "1022", "label": "Филиал"}],
        )

    def test_memorial_order_adds_one_task_for_all_employees(self) -> None:
        service = ReportService(insecure=False)
        service.add(
            "memorial_order",
            {
                "branch_id": "1022",
                "office_id": "1057",
                "report_date": "15.09.2026",
            },
        )
        queue = service.queue()
        self.assertEqual(len(queue), 1)
        self.assertEqual(queue[0]["kind"], "memorial_order")
        self.assertEqual(queue[0]["values"]["fields"]["Value"], "XLS")
        self.assertEqual(queue[0]["values"]["fields"]["User.All"], "True")
        self.assertEqual(MEMORIAL_ORDER_REPORT, "Сводный мемориальный ордер")

    def test_memorial_order_download_keeps_abs_file_unmodified(self) -> None:
        class FakeClient:
            def execute_report(self, *args: object, **kwargs: object) -> ReportDownloadResult:
                path = Path(args[2]) / "report.xls"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"test")
                return ReportDownloadResult("report.xls", path, "application/vnd.ms-excel", "https://example.test")

        service = ReportService(insecure=False)
        service.client = FakeClient()  # type: ignore[assignment]
        service.add(
            "memorial_order",
            {"branch_id": "1022", "office_id": "1057", "report_date": "15.09.2026"},
        )
        with TemporaryDirectory() as directory:
            paths = service.download(directory)
        self.assertEqual(len(paths), 1)
