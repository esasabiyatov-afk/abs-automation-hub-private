from __future__ import annotations

import importlib.util
import inspect
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True)
class PluginContext:
    run_id: int
    task_id: int
    source: dict[str, Any] | None
    records: list[dict[str, Any]]
    artifacts_dir: Path


@dataclass(frozen=True)
class ArtifactOutput:
    name: str
    path: Path
    mime_type: str = "application/octet-stream"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PluginResult:
    records: list[dict[str, Any]] = field(default_factory=list)
    artifacts: list[ArtifactOutput] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)


class AutomationPlugin(Protocol):
    name: str
    description: str

    def run(self, context: PluginContext, params: dict[str, Any]) -> PluginResult: ...


class PluginRegistry:
    def __init__(self) -> None:
        self._plugins: dict[str, AutomationPlugin] = {}

    def register(self, plugin: AutomationPlugin) -> None:
        name = getattr(plugin, "name", "").strip()
        if not name:
            raise ValueError("Plugin must define a non-empty name")
        if name in self._plugins:
            raise ValueError(f"Duplicate plugin: {name}")
        self._plugins[name] = plugin

    def get(self, name: str) -> AutomationPlugin:
        try:
            return self._plugins[name]
        except KeyError as exc:
            raise KeyError(f"Unknown plugin: {name}") from exc

    def describe(self) -> list[dict[str, str]]:
        return [
            {"name": name, "description": getattr(plugin, "description", "")}
            for name, plugin in sorted(self._plugins.items())
        ]

    def load_directory(self, directory: str | Path) -> None:
        plugin_dir = Path(directory)
        if not plugin_dir.exists():
            return
        for path in sorted(plugin_dir.glob("*.py")):
            if path.name.startswith("_"):
                continue
            module_name = f"automation_hub_external_{path.stem}"
            spec = importlib.util.spec_from_file_location(module_name, path)
            if spec is None or spec.loader is None:
                raise ImportError(f"Cannot load plugin module: {path}")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            plugin = getattr(module, "plugin", None)
            if plugin is None or not callable(getattr(plugin, "run", None)):
                raise TypeError(f"{path} must export a plugin object with run()")
            if inspect.isclass(plugin):
                plugin = plugin()
            self.register(plugin)

