"""Disposable real services, scripted model and session cookies for browser tests.

Never opens the developer's wiki, credentials, index or model. All content and
service state live in a TemporaryDirectory and disappear on shutdown.
"""

import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any

import uvicorn
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))

from agent_helpers import agent_config, seed_chat, tokens, wiki_client
from fake_llm import FakeLLM, claim

from wikiagent.api import create_app as agent_app
from wikiagent.models import ModelClient
from wikiagent.state import AgentState
from wikisvc.config import Settings
from wikisvc.domain.markdown import render
from wikisvc.domain.validate import parse_page
from wikisvc.main import create_app
from wikisvc.services.auth import Auth
from wikisvc.services.initialize import initialize
from wikisvc.storage.gitrepo import GitRepo
from wikisvc.storage.safefs import SafeFS


def respond(task: str, data: dict[str, Any]) -> dict[str, Any]:
    if task == "route":
        return {"intent": "intake"}
    if task == "extract_claims":
        return {"claims": [claim("rule-browser-async")]}
    if task == "classify":
        return {"relations": [{"relation": "new", "confidence": 0.95, "reason": "Новое правило."}]}
    raise AssertionError(task)


def main() -> None:
    stopped = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stopped.set())
    with tempfile.TemporaryDirectory(prefix="wiki-ui-e2e-") as directory:
        base = Path(directory)
        config = Settings(
            wiki_root=base / "wiki", state_dir=base / "state", index_dir=base / "index"
        )
        config.session_issuer_token_name = "wiki-ui"
        config.roles_file = base / "roles.yaml"
        config.roles_file.write_text(
            "groups:\n  human: {role: reviewer, clearance: restricted}\n"
            "  reviewer: {role: reviewer, clearance: restricted}\n"
            "  reader: {role: reader, clearance: internal}\n"
        )
        initialize(config.wiki_root)
        source, target = SafeFS(ROOT / "tests/fixtures/wiki"), SafeFS(config.wiki_root)
        for path in source.files("**/*"):
            target.write(path, source.read(path))
        GitRepo(config.wiki_root).commit("Browser test fixtures", "fixtures")
        app = create_app(config)
        with TestClient(app) as client:
            agent, _ = tokens(client)
            auth = Auth(app.state.runtime.state)
            issuer = auth.create("wiki-ui", "reader", "public")
            secret_file = base / "oidc.secret"
            secret_file.write_text("local-test-secret")
            token_file = base / "issuer.token"
            token_file.write_text(issuer)
            seed_chat(client, config)
            titles = {
                "rule-http-requests-sync": "HTTP-запросы в Python",
                "rule-python-type-hints": "Явные типы на границах системы",
                "pat-fastapi-sync-endpoint": "Обработчик запросов FastAPI",
                "term-orphan": "Единый язык команды",
            }
            # Only this temporary corpus is modified directly; production uses the API.
            for path in target.files("wiki/**/*.md"):
                content = target.read(path)
                if not content.startswith("---"):
                    continue
                parsed = parse_page(content, path)
                if parsed.id in titles:
                    meta = parsed.frontmatter.model_dump(mode="json")
                    meta["title"] = titles[parsed.id]
                    target.write(path, render(meta, parsed.body_md))
            GitRepo(config.wiki_root).commit("Name browser fixtures", "fixtures")
            app.state.runtime.reindex()
            os.environ["WIKIAGENT_TOKEN"] = agent
            settings = agent_config(base / "agent")
            settings.heal.enabled = False
            wiki = wiki_client(client, settings)
            models = ModelClient(settings, AgentState(settings.state_dir), FakeLLM(respond).http)
            agent_service = agent_app(settings, wiki, models)
            folder = ROOT / "ui/.e2e"
            folder.mkdir(exist_ok=True)
            credentials = folder / "config.json"
            credentials.write_text(json.dumps({"issuer": issuer}))
            credentials.chmod(0o600)
            servers = [
                uvicorn.Server(
                    uvicorn.Config(
                        app, host="127.0.0.1", port=18787, lifespan="off", log_level="warning"
                    )
                ),
                uvicorn.Server(
                    uvicorn.Config(agent_service, host="127.0.0.1", port=18788, log_level="warning")
                ),
            ]
            threads = [threading.Thread(target=server.run, daemon=True) for server in servers]
            for thread in threads:
                thread.start()
            env = {
                **os.environ,
                "WIKI_UI_BIND": "127.0.0.1:18789",
                "WIKI_UI_WIKISVC_URL": "http://127.0.0.1:18787",
                "WIKI_UI_AGENT_URL": "http://127.0.0.1:18788",
                "WIKI_UI_OIDC_ISSUER": "http://127.0.0.1:18790",
                "WIKI_UI_OIDC_CLIENT_ID": "browser-test",
                "WIKI_UI_OIDC_SECRET_FILE": str(secret_file),
                "WIKI_UI_SESSION_TOKEN_FILE": str(token_file),
                "WIKI_UI_OIDC_REDIRECT_URL": "http://127.0.0.1:18789/auth/callback",
                "WIKI_UI_OIDC_INSECURE_HTTP": "1",
                "WIKI_UI_COOKIE_SECURE": "0",
            }
            try:
                with subprocess.Popen([str(folder / "wiki-ui")], env=env) as process:
                    try:
                        while not stopped.wait(0.2):
                            if process.poll() is not None:
                                raise RuntimeError("UI server stopped")
                    finally:
                        process.terminate()
                        process.wait(timeout=20)
            finally:
                for server in servers:
                    server.should_exit = True
                for thread in threads:
                    thread.join(timeout=20)
                credentials.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
