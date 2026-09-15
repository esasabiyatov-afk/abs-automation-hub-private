from __future__ import annotations

import csv

from automation_hub.plugins import ArtifactOutput, PluginContext, PluginResult


class ExampleReportPlugin:
    name = "example.client_summary"
    description = "Creates a CSV summary from records already stored for a source"

    def run(self, context: PluginContext, params: dict) -> PluginResult:
        output = context.artifacts_dir / "client-summary.csv"
        output.parent.mkdir(parents=True, exist_ok=True)
        fields = params.get("fields", ["external_id"])
        with output.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            for stored in context.records:
                payload = stored.get("payload", {})
                row = {**payload, "external_id": stored["external_id"]}
                writer.writerow(row)
        return PluginResult(
            artifacts=[ArtifactOutput("client-summary.csv", output, "text/csv")],
            metrics={"rows_written": len(context.records)},
        )


plugin = ExampleReportPlugin()

