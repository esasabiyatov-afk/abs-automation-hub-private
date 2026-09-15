from __future__ import annotations

import json
from pathlib import Path

from automation_hub.plugins import PluginContext, PluginResult


class ExampleImportPlugin:
    name = "example.json_import"
    description = "Imports a JSON array from a configured local file"

    def run(self, context: PluginContext, params: dict) -> PluginResult:
        if context.source is None:
            raise ValueError("json_import requires a source")
        path = Path(context.source["config"]["path"]).expanduser().resolve()
        id_field = params.get("id_field", "id")
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise ValueError("Input JSON must contain an array")
        records = []
        for item in data:
            if not isinstance(item, dict) or id_field not in item:
                raise ValueError(f"Every item must be an object containing {id_field!r}")
            records.append({"external_id": str(item[id_field]), "payload": item})
        return PluginResult(records=records, metrics={"rows_read": len(records)})


plugin = ExampleImportPlugin()

