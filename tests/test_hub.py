from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from automation_hub.db import Database
from automation_hub.plugins import PluginRegistry
from automation_hub.readonly import ActionApproval, ReadOnlyPolicy
from automation_hub.service import HubService


class HubTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        registry = PluginRegistry()
        registry.load_directory(Path(__file__).parents[1] / "plugins")
        self.hub = HubService(Database(self.root / "hub.db"), registry, self.root / "artifacts")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_import_is_idempotent_and_report_is_created(self) -> None:
        input_path = self.root / "clients.json"
        input_path.write_text(
            json.dumps([{"id": 1, "name": "A"}, {"id": 2, "name": "B"}]),
            encoding="utf-8",
        )
        source = self.hub.create_source("clients", "json", {"path": str(input_path)})
        importer = self.hub.create_task("import", "example.json_import", source["id"], {"id_field": "id"})

        first = self.hub.run_task(importer["id"])
        second = self.hub.run_task(importer["id"])
        self.assertEqual(first["metrics"]["records_inserted"], 2)
        self.assertEqual(second["metrics"]["records_inserted"], 0)
        self.assertEqual(len(self.hub.list_records(source["id"])), 2)

        report = self.hub.create_task(
            "report", "example.client_summary", source["id"], {"fields": ["external_id", "name"]}
        )
        report_run = self.hub.run_task(report["id"])
        self.assertEqual(report_run["status"], "succeeded")
        self.assertEqual(len(report_run["artifacts"]), 1)
        self.assertTrue(Path(report_run["artifacts"][0]["path"]).is_file())

    def test_read_only_policy_fails_closed(self) -> None:
        policy = ReadOnlyPolicy("https://bank.example/app/")
        self.assertEqual(
            policy.validate("GET", "/app/Customers/Search"),
            "https://bank.example/app/Customers/Search",
        )
        with self.assertRaises(PermissionError):
            policy.validate("POST", "/app/Customers/Search")
        with self.assertRaises(PermissionError):
            policy.validate("GET", "/app/Customers/Delete/1")
        with self.assertRaises(PermissionError):
            policy.validate("GET", "https://other.example/data")

    def test_explicit_report_post_allowlist(self) -> None:
        policy = ReadOnlyPolicy(
            "https://bank.example/app/",
            allowed_post_paths=frozenset({"/app/Reports/Download"}),
        )
        self.assertEqual(
            policy.validate("POST", "/app/Reports/Download"),
            "https://bank.example/app/Reports/Download",
        )

    def test_write_requires_exact_one_time_approval(self) -> None:
        policy = ReadOnlyPolicy("https://bank.example/app/")
        approval = ActionApproval(
            method="POST",
            path="/app/Customers/Edit",
            allowed_fields=frozenset({"Phone", "Email"}),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=2),
            reason="User approved updating contact details",
        )
        self.assertEqual(
            policy.validate(
                "POST",
                "/app/Customers/Edit",
                field_names={"Phone", "Email"},
                approval=approval,
            ),
            "https://bank.example/app/Customers/Edit",
        )
        with self.assertRaises(PermissionError):
            policy.validate(
                "POST",
                "/app/Customers/Edit",
                field_names={"Phone"},
                approval=approval,
            )

    def test_approval_cannot_authorize_delete_or_extra_fields(self) -> None:
        policy = ReadOnlyPolicy("https://bank.example/app/")
        approval = ActionApproval(
            method="POST",
            path="/app/Customers/Edit",
            allowed_fields=frozenset({"Phone"}),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=2),
            reason="User approved one field",
        )
        with self.assertRaises(PermissionError):
            policy.validate(
                "POST",
                "/app/Customers/Edit",
                field_names={"Phone", "Email"},
                approval=approval,
            )
        delete_approval = ActionApproval(
            method="DELETE",
            path="/app/Customers/Delete",
            allowed_fields=frozenset(),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=2),
            reason="Must remain ineffective",
        )
        with self.assertRaises(PermissionError):
            policy.validate("DELETE", "/app/Customers/Delete", approval=delete_approval)


if __name__ == "__main__":
    unittest.main()
