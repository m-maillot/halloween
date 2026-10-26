"""Faux serveur HTTP Home Assistant (stdlib, dans un fil) pour les tests.

Enregistre chaque requête (méthode, chemin, jeton, corps JSON) et répond comme l'API REST :
`GET /api/`, `GET /api/states[/<id>]`, `POST /api/services/<domaine>/<service>`.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

TOKEN = "jeton-de-test"


@dataclass
class Recorded:
    method: str
    path: str
    token: str | None
    body: Any = None


@dataclass
class FakeHA:
    token: str = TOKEN
    requests: list[Recorded] = field(default_factory=list)
    states: list[dict[str, Any]] = field(default_factory=list)
    # (méthode, chemin) -> (statut, corps) pour forcer une réponse
    overrides: dict[tuple[str, str], tuple[int, Any]] = field(default_factory=dict)
    delay_s: float = 0.0
    _server: ThreadingHTTPServer | None = None

    @property
    def url(self) -> str:
        assert self._server is not None
        return f"http://127.0.0.1:{self._server.server_address[1]}"

    def posts(self, path_prefix: str = "/api/services/") -> list[Recorded]:
        return [r for r in self.requests if r.method == "POST" and r.path.startswith(path_prefix)]

    def start(self) -> FakeHA:
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args: Any) -> None:  # silence
                pass

            def _handle(self, method: str) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b""
                body = json.loads(raw) if raw else None
                header = self.headers.get("Authorization") or ""
                token = header.removeprefix("Bearer ") if header.startswith("Bearer ") else None
                outer.requests.append(Recorded(method, self.path, token, body))
                if outer.delay_s:
                    time.sleep(outer.delay_s)
                status, payload = outer._route(method, self.path, token)
                data = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self) -> None:
                self._handle("GET")

            def do_POST(self) -> None:
                self._handle("POST")

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(
            target=self._server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
        ).start()
        return self

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None

    def _route(self, method: str, path: str, token: str | None) -> tuple[int, Any]:
        if token != self.token:
            return 401, {"message": "401: Unauthorized"}
        if (method, path) in self.overrides:
            return self.overrides[(method, path)]
        if method == "GET" and path == "/api/":
            return 200, {"message": "API running."}
        if method == "GET" and path == "/api/states":
            return 200, self.states
        if method == "GET" and path.startswith("/api/states/"):
            entity_id = path.removeprefix("/api/states/")
            found = next((s for s in self.states if s["entity_id"] == entity_id), None)
            return (200, found) if found else (404, {"message": "Entity not found."})
        if method == "POST" and path.startswith("/api/services/"):
            return 200, []
        return 404, {"message": "404: Not Found"}
