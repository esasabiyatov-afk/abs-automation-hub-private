from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from .db import Database
from .plugins import ArtifactOutput, PluginContext, PluginRegistry


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _decode_row(row: Any) -> dict[str, Any]:
    result = dict(row)
    for key in ("config_json", "params_json", "metrics_json", "metadata_json", "details_json", "payload_json"):
        if key in result:
            result[key.removesuffix("_json")] = json.loads(result.pop(key))
    for key in ("enabled",):
        if key in result:
            result[key] = bool(result[key])
    return result


class HubService:
    def __init__(self, database: Database, registry: PluginRegistry, artifacts_dir: str | Path):
        self.database = database
        self.registry = registry
        self.artifacts_dir = Path(artifacts_dir).expanduser().resolve()
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self.database.initialize()

    def _audit(self, connection: Any, action: str, entity_type: str, entity_id: Any, details: Any) -> None:
        connection.execute(
            "INSERT INTO audit_log(action, entity_type, entity_id, details_json) VALUES (?, ?, ?, ?)",
            (action, entity_type, None if entity_id is None else str(entity_id), _json(details)),
        )

    def create_source(self, name: str, kind: str, config: dict[str, Any] | None = None) -> dict[str, Any]:
        with self.database.transaction() as connection:
            cursor = connection.execute(
                "INSERT INTO sources(name, kind, config_json) VALUES (?, ?, ?)",
                (name.strip(), kind.strip(), _json(config or {})),
            )
            source_id = cursor.lastrowid
            self._audit(connection, "create", "source", source_id, {"name": name, "kind": kind})
            row = connection.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
        return _decode_row(row)

    def list_sources(self) -> list[dict[str, Any]]:
        with self.database.read() as connection:
            rows = connection.execute("SELECT * FROM sources ORDER BY id").fetchall()
        return [_decode_row(row) for row in rows]

    def create_task(
        self,
        name: str,
        plugin: str,
        source_id: int | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.registry.get(plugin)
        with self.database.transaction() as connection:
            cursor = connection.execute(
                "INSERT INTO tasks(name, plugin, source_id, params_json) VALUES (?, ?, ?, ?)",
                (name.strip(), plugin, source_id, _json(params or {})),
            )
            task_id = cursor.lastrowid
            self._audit(connection, "create", "task", task_id, {"name": name, "plugin": plugin})
            row = connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return _decode_row(row)

    def list_tasks(self) -> list[dict[str, Any]]:
        with self.database.read() as connection:
            rows = connection.execute("SELECT * FROM tasks ORDER BY id").fetchall()
        return [_decode_row(row) for row in rows]

    def list_runs(self, limit: int = 100) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 1000))
        with self.database.read() as connection:
            rows = connection.execute("SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [_decode_row(row) for row in rows]

    def get_run(self, run_id: int) -> dict[str, Any] | None:
        with self.database.read() as connection:
            row = connection.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
            if row is None:
                return None
            artifacts = connection.execute("SELECT * FROM artifacts WHERE run_id = ? ORDER BY id", (run_id,)).fetchall()
        result = _decode_row(row)
        result["artifacts"] = [_decode_row(item) for item in artifacts]
        return result

    def list_records(self, source_id: int, limit: int = 100) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 1000))
        with self.database.read() as connection:
            rows = connection.execute(
                "SELECT * FROM records WHERE source_id = ? ORDER BY id DESC LIMIT ?",
                (source_id, limit),
            ).fetchall()
        return [_decode_row(row) for row in rows]

    def _store_record(self, connection: Any, source_id: int, record: dict[str, Any]) -> bool:
        external_id = str(record.get("external_id", "")).strip()
        if not external_id:
            raise ValueError("Every plugin record must contain external_id")
        payload = record.get("payload", record)
        payload_json = _json(payload)
        checksum = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
        cursor = connection.execute(
            "INSERT OR IGNORE INTO records(source_id, external_id, payload_json, checksum) VALUES (?, ?, ?, ?)",
            (source_id, external_id, payload_json, checksum),
        )
        return cursor.rowcount == 1

    def _store_artifact(self, connection: Any, run_id: int, artifact: ArtifactOutput) -> None:
        source_path = artifact.path.expanduser().resolve()
        if not source_path.is_file():
            raise FileNotFoundError(source_path)
        run_dir = self.artifacts_dir / str(run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        destination = run_dir / Path(artifact.name).name
        if source_path != destination:
            shutil.copy2(source_path, destination)
        connection.execute(
            "INSERT INTO artifacts(run_id, name, mime_type, path, metadata_json) VALUES (?, ?, ?, ?, ?)",
            (run_id, destination.name, artifact.mime_type, str(destination), _json(artifact.metadata)),
        )

    def run_task(self, task_id: int) -> dict[str, Any]:
        with self.database.transaction() as connection:
            task_row = connection.execute("SELECT * FROM tasks WHERE id = ? AND enabled = 1", (task_id,)).fetchone()
            if task_row is None:
                raise KeyError(f"Enabled task not found: {task_id}")
            task = _decode_row(task_row)
            source = None
            if task["source_id"] is not None:
                source_row = connection.execute("SELECT * FROM sources WHERE id = ? AND enabled = 1", (task["source_id"],)).fetchone()
                if source_row is None:
                    raise KeyError(f"Enabled source not found: {task['source_id']}")
                source = _decode_row(source_row)
            cursor = connection.execute("INSERT INTO runs(task_id, status) VALUES (?, 'queued')", (task_id,))
            run_id = cursor.lastrowid
            connection.execute("UPDATE runs SET status = 'running', started_at = CURRENT_TIMESTAMP WHERE id = ?", (run_id,))
            self._audit(connection, "start", "run", run_id, {"task_id": task_id})

        plugin = self.registry.get(task["plugin"])
        records = self.list_records(task["source_id"], 1000) if task["source_id"] is not None else []
        context = PluginContext(
            run_id=run_id,
            task_id=task_id,
            source=source,
            records=records,
            artifacts_dir=self.artifacts_dir / "tmp" / str(run_id),
        )
        context.artifacts_dir.mkdir(parents=True, exist_ok=True)

        try:
            result = plugin.run(context, task["params"])
            inserted = 0
            with self.database.transaction() as connection:
                if result.records and source is None:
                    raise ValueError("A task that returns records must have a source")
                for record in result.records:
                    inserted += int(self._store_record(connection, source["id"], record))
                for artifact in result.artifacts:
                    self._store_artifact(connection, run_id, artifact)
                metrics = {**result.metrics, "records_received": len(result.records), "records_inserted": inserted}
                connection.execute(
                    "UPDATE runs SET status = 'succeeded', finished_at = CURRENT_TIMESTAMP, metrics_json = ? WHERE id = ?",
                    (_json(metrics), run_id),
                )
                self._audit(connection, "finish", "run", run_id, {"status": "succeeded", "metrics": metrics})
        except Exception as exc:
            with self.database.transaction() as connection:
                connection.execute(
                    "UPDATE runs SET status = 'failed', finished_at = CURRENT_TIMESTAMP, error = ? WHERE id = ?",
                    (str(exc), run_id),
                )
                self._audit(connection, "finish", "run", run_id, {"status": "failed", "error": str(exc)})
            raise
        return self.get_run(run_id)
