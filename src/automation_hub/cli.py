from __future__ import annotations

import argparse
import os
from pathlib import Path

from .api import serve
from .db import Database
from .plugins import PluginRegistry
from .service import HubService


def build_hub(root: Path, plugin_dirs: list[str]) -> HubService:
    registry = PluginRegistry()
    for directory in plugin_dirs:
        registry.load_directory(directory)
    return HubService(Database(root / "hub.db"), registry, root / "artifacts")


def main() -> None:
    parser = argparse.ArgumentParser(description="Automation Hub")
    parser.add_argument("--root", default=os.getenv("HUB_ROOT", ".hub"))
    parser.add_argument("--plugins", action="append")
    parser.add_argument("--host", default=os.getenv("HUB_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("HUB_PORT", "8765")))
    args = parser.parse_args()
    token = os.getenv("HUB_API_TOKEN", "")
    if not token:
        raise SystemExit("Set HUB_API_TOKEN before starting the service")
    hub = build_hub(Path(args.root).resolve(), args.plugins or ["plugins"])
    serve(hub, args.host, args.port, token)


if __name__ == "__main__":
    main()
