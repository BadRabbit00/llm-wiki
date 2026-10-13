"""A scripted llm-wiki-updater on a Unix socket, for the browser flow only.

The daemon itself is tested in Go and in a NixOS VM. This one offers v0.3.0,
accepts that digest alone and completes a few update steps per status request,
so the page sees progress and then the outcome.
"""

import json
import socketserver
import threading
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any

CURRENT = {"tag": "v0.2.0", "digest": "sha256:" + "a" * 64, "revision": "aaaaaaa"}
OFFER = {"tag": "v0.3.0", "digest": "sha256:" + "b" * 64, "revision": "bbbbbbb"}
STEPS = [
    "pull", "verify", "jobs-before", "stop", "archive",
    "switch", "migrate", "start", "health", "jobs-after",
]  # fmt: skip


class FakeUpdater:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.polls = 0
        self.state: dict[str, Any] = {
            "channel": "release",
            "current": CURRENT,
            "available": OFFER,
            "checked_at": "2026-10-13T09:00:00Z",
            "operation": None,
        }

    def status(self) -> dict[str, Any]:
        with self.lock:
            operation = self.state["operation"]
            if operation and operation["state"] == "running":
                self.polls += 1
                done = min(self.polls * 3, len(STEPS))
                operation["steps"] = [
                    {"name": name, "status": "done", "at": "2026-10-13T09:01:00Z"}
                    for name in STEPS[:done]
                ]
                if done == len(STEPS):
                    operation.update(state="succeeded", finished_at="2026-10-13T09:05:00Z")
                    self.state.update(current=OFFER, available=None)
            snapshot: dict[str, Any] = json.loads(json.dumps(self.state))
            return snapshot

    def apply(self, digest: str) -> bool:
        with self.lock:
            if not self.state["available"] or digest != self.state["available"]["digest"]:
                return False
            self.state["operation"] = {
                "id": "20261013T090100Z",
                "from": CURRENT,
                "to": OFFER,
                "started_by": "opaque-admin",
                "state": "running",
                "steps": [],
                "jobs_before": [{"id": "j1", "kind": "ingest_book", "status": "running"}],
                "jobs_after": [{"id": "j1", "kind": "ingest_book", "status": "running"}],
                "archive": "/var/backups/llm-wiki/pre-update-20261013T090100Z-v0.3.0.tar.gz",
                "started_at": "2026-10-13T09:01:00Z",
            }
            return True


class Handler(BaseHTTPRequestHandler):
    updater: FakeUpdater

    def log_message(self, format: str, *args: Any) -> None:
        """Unix sockets have no client address to log."""

    def reply(self, status: int, body: dict[str, Any]) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        parsed: dict[str, Any] = json.loads(self.rfile.read(length) or b"{}")
        return parsed

    def authorized(self) -> bool:
        if self.headers.get("Authorization", "").startswith("Bearer "):
            return True
        self.reply(401, {"error": {"code": "E_UNAUTHORIZED", "message": "Войдите в систему."}})
        return False

    def do_GET(self) -> None:
        if self.authorized():
            self.reply(200, self.updater.status())

    def do_POST(self) -> None:
        if not self.authorized():
            return
        if self.path == "/v1/apply":
            if not self.updater.apply(self.body().get("digest", "")):
                self.reply(409, {"error": {"code": "E_UPDATE_STALE", "message": "Устарело."}})
                return
            self.reply(202, self.updater.status())
            return
        self.reply(200, self.updater.status())

    def do_PUT(self) -> None:
        if self.authorized():
            with self.updater.lock:
                self.updater.state["channel"] = self.body().get("channel", "release")
            self.reply(200, self.updater.status())


class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True


def serve(path: Path) -> Server:
    handler = type("ScriptedHandler", (Handler,), {"updater": FakeUpdater()})
    server = Server(str(path), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server
