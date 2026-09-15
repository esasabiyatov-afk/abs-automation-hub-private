from __future__ import annotations

import unittest

from tolubay_reports_app import form_defaults


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
