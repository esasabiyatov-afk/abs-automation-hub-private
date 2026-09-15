from __future__ import annotations

import hmac
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from .service import HubService


class HubRequestHandler(BaseHTTPRequestHandler):
    server_version = "AutomationHub/0.1"

    @property
    def hub(self) -> HubService:
        return self.server.hub  # type: ignore[attr-defined]

    @property
    def api_token(self) -> str:
        return self.server.api_token  # type: ignore[attr-defined]

    def _authorized(self) -> bool:
        if not self.api_token:
            return True
        header = self.headers.get("Authorization", "")
        return hmac.compare_digest(header, f"Bearer {self.api_token}")

    def _send(self, status: int, body: Any) -> None:
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def _body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length > 1_000_000:
            raise ValueError("Request body exceeds 1 MB")
        raw = self.rfile.read(length) if length else b"{}"
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError("JSON body must be an object")
        return value

    def _dispatch(self, method: str) -> tuple[int, Any]:
        parsed = urlparse(self.path)
        parts = [part for part in parsed.path.split("/") if part]
        query = parse_qs(parsed.query)

        if method == "GET" and parts == ["health"]:
            return HTTPStatus.OK, {"status": "ok"}
        if method == "GET" and parts == ["plugins"]:
            return HTTPStatus.OK, self.hub.registry.describe()
        if method == "GET" and parts == ["sources"]:
            return HTTPStatus.OK, self.hub.list_sources()
        if method == "POST" and parts == ["sources"]:
            body = self._body()
            return HTTPStatus.CREATED, self.hub.create_source(body["name"], body["kind"], body.get("config"))
        if method == "GET" and parts == ["tasks"]:
            return HTTPStatus.OK, self.hub.list_tasks()
        if method == "POST" and parts == ["tasks"]:
            body = self._body()
            return HTTPStatus.CREATED, self.hub.create_task(
                body["name"], body["plugin"], body.get("source_id"), body.get("params")
            )
        if method == "GET" and parts == ["runs"]:
            return HTTPStatus.OK, self.hub.list_runs(int(query.get("limit", ["100"])[0]))
        if method == "GET" and len(parts) == 2 and parts[0] == "runs":
            run = self.hub.get_run(int(parts[1]))
            return (HTTPStatus.OK, run) if run else (HTTPStatus.NOT_FOUND, {"error": "Run not found"})
        if method == "POST" and len(parts) == 3 and parts[0] == "tasks" and parts[2] == "run":
            return HTTPStatus.OK, self.hub.run_task(int(parts[1]))
        if method == "GET" and parts == ["records"]:
            if "source_id" not in query:
                raise ValueError("source_id is required")
            return HTTPStatus.OK, self.hub.list_records(
                int(query["source_id"][0]), int(query.get("limit", ["100"])[0])
            )
        return HTTPStatus.NOT_FOUND, {"error": "Route not found"}

    def _handle(self, method: str) -> None:
        if not self._authorized():
            self._send(HTTPStatus.UNAUTHORIZED, {"error": "Invalid or missing bearer token"})
            return
        try:
            status, body = self._dispatch(method)
            self._send(status, body)
        except (KeyError, ValueError, json.JSONDecodeError) as exc:
            self._send(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        except Exception as exc:
            self._send(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})

    def do_GET(self) -> None:  # noqa: N802
        self._handle("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._handle("POST")

    def log_message(self, format: str, *args: Any) -> None:
        return


def serve(hub: HubService, host: str, port: int, api_token: str) -> None:
    server = ThreadingHTTPServer((host, port), HubRequestHandler)
    server.hub = hub  # type: ignore[attr-defined]
    server.api_token = api_token  # type: ignore[attr-defined]
    print(f"Automation Hub listening on http://{host}:{port}")
    server.serve_forever()

