"""Opt-in live-model smoke test; all wiki/state data lives in a temporary directory."""

import argparse
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

import httpx
from fastapi.testclient import TestClient

from wikiagent.api import create_app as agent_app
from wikiagent.client import WikiClient
from wikiagent.config import load_config
from wikisvc.config import Settings
from wikisvc.main import create_app
from wikisvc.services.auth import Auth
from wikisvc.services.initialize import initialize


def response_json(response: httpx.Response) -> dict[str, Any]:
    response.raise_for_status()
    return dict(response.json())


def wait_job(api: TestClient, job_id: str) -> dict[str, Any]:
    deadline = time.monotonic() + 1800
    while time.monotonic() < deadline:
        job = response_json(api.get("/jobs/" + job_id))
        if job["status"] not in ("pending", "running", "waiting_chat"):
            return job
        time.sleep(0.25)
    raise TimeoutError("Live-model job did not finish in 30 minutes")


def run(config_path: Path, out: Path) -> None:
    config = load_config(config_path)
    report: dict[str, Any] = {
        "models": {r: m.model for r, m in config.models.items()},
        "isolated_wiki": True,
        "checks": {},
    }

    def save(name: str, result: dict[str, Any]) -> None:
        report["checks"][name] = result
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        print(name + ": " + str(result.get("pass", False)), flush=True)

    with tempfile.TemporaryDirectory(prefix="wikiagent-live-") as directory:
        root = Path(directory)
        settings = Settings(
            wiki_root=root / "wiki", state_dir=root / "state", index_dir=root / "index"
        )
        initialize(settings.wiki_root)
        config.state_dir = root / "agent"
        config.heal.enabled = False
        config.heal.max_model_calls_per_run = 12
        config.heal.windows = []
        config.limits.chapter_chunk_tokens = 1000
        with TestClient(create_app(settings)) as wiki:
            auth = Auth(wiki.app.state.runtime.state)
            agent = auth.create(
                "live-agent", "writer", "restricted", person="live-agent", kind="agent"
            )
            human = auth.create(
                "live-human", "reviewer", "restricted", person="live-human", kind="human"
            )
            os.environ[config.wikisvc.token_env] = agent
            wiki.headers["Authorization"] = "Bearer " + agent

            def forward(request: httpx.Request) -> httpx.Response:
                response = wiki.request(
                    request.method,
                    str(request.url),
                    headers=dict(request.headers),
                    content=request.content,
                )
                return httpx.Response(
                    response.status_code,
                    content=response.content,
                    headers={"Content-Type": "application/json"},
                )

            client = WikiClient(
                config.wikisvc,
                http=httpx.Client(
                    base_url="http://testserver", transport=httpx.MockTransport(forward)
                ),
            )

            def seed_rule(page_id: str, summary: str) -> None:
                pid = response_json(
                    wiki.post("/api/v1/proposals", json={"title": "Fixture for local model"})
                )["pid"]
                response_json(
                    wiki.put(
                        f"/api/v1/proposals/{pid}/pages/{page_id}",
                        json={
                            "frontmatter": {
                                "id": page_id,
                                "type": "rule",
                                "title": summary,
                                "summary": summary,
                                "category": "architecture",
                                "origin": "team",
                                "applies_to": ["lang:python"],
                                "aliases": ["сетевые запросы", "HTTP Python"],
                            },
                            "body_md": "## Правило\n\n"
                            + summary
                            + "\n\n## Обоснование\n\nРешение команды для тестового проекта.\n\n## Примеры\n\n"
                            + summary,
                        },
                    )
                )
                response_json(
                    wiki.post(
                        f"/api/v1/proposals/{pid}/accept",
                        headers={"Authorization": "Bearer " + human},
                        json={
                            "promote": [
                                {"id": page_id, "level": "should", "applies_to": ["lang:python"]}
                            ]
                        },
                    )
                )

            seed_rule(
                "rule-http-requests-sync",
                "Используй requests для синхронных HTTP запросов в обработчиках Python.",
            )
            with TestClient(agent_app(config, client)) as api:
                api.headers["Authorization"] = "Bearer " + human
                session = response_json(
                    api.post("/chat/sessions", json={"profile": "python-fastapi"})
                )
                reply = api.post(
                    "/chat/sessions/" + session["id"] + "/messages",
                    json={
                        "text": "Мы используем FastAPI и только async код в обработчиках Python."
                    },
                )
                events = [
                    json.loads(block.split("data: ", 1)[1])
                    for block in reply.text.split("\n\n")
                    if block.startswith(("event: message\n", "event: error\n"))
                ]
                result = events[-1] if events else {}
                plan = result.get("plan") or {}
                if plan.get("proposal"):
                    proposal = client.request("GET", "/proposals/" + plan["proposal"])
                    valid = client.request("GET", "/proposals/" + plan["proposal"] + "/validate")
                    save(
                        "chat",
                        {
                            "pass": proposal["status"] == "draft" and not valid["errors"],
                            "status": proposal["status"],
                            "items": [
                                {k: i.get(k) for k in ("action", "target", "thesis")}
                                for i in plan["items"]
                            ],
                            "questions": plan["questions"],
                            "errors": valid["errors"],
                        },
                    )
                else:
                    save("chat", {"pass": False, "result": result})
                # Only the fixture code acting as the human seeds main. Models never accept.
                seed_rule(
                    "rule-http-async",
                    "Выполняй HTTP запросы в обработчиках Python асинхронно; синхронные requests не используй.",
                )
                heal = response_json(api.post("/jobs/heal", json={"scope": "full"}))
                heal = wait_job(api, heal["id"])
                findings = client.all("/findings")
                semantic = [f for f in findings if f["kind"] == "conflicts"]
                save(
                    "heal",
                    {
                        "pass": heal["status"] == "done"
                        and bool(semantic)
                        and all(f["proposal_pid"] for f in semantic),
                        "status": heal["status"],
                        "error": heal["error"],
                        "progress": heal["progress"],
                        "findings": [
                            {k: f[k] for k in ("kind", "summary", "proposal_pid")} for f in findings
                        ],
                    },
                )
                fixture = Path(__file__).resolve().parents[1] / "tests/fixtures/books/handbook.epub"
                raw = response_json(
                    wiki.post(
                        "/api/v1/raw",
                        files={"file": ("handbook.epub", fixture.read_bytes())},
                        data={"category": "library"},
                    )
                )
                book = response_json(
                    api.post(
                        "/jobs/ingest-book",
                        json={
                            "raw_path": raw["path"],
                            "title": "Original fixture handbook",
                            "scopes_hint": ["lang:python"],
                        },
                    )
                )
                book = wait_job(api, book["id"])
                progress = book["progress"]
                candidates = []
                errors = []
                if progress.get("proposal"):
                    proposal = client.request("GET", "/proposals/" + progress["proposal"])
                    candidates = [p for p in proposal["pages"] if p["type"] == "rule"]
                    errors = client.request(
                        "GET", "/proposals/" + progress["proposal"] + "/validate"
                    )["errors"]
                save(
                    "book",
                    {
                        "pass": book["status"] == "awaiting_review"
                        and bool(candidates)
                        and all(p["lifecycle"] == "candidate" for p in candidates)
                        and not errors,
                        "status": book["status"],
                        "error": book["error"],
                        "progress": progress,
                        "candidates": [
                            {k: p[k] for k in ("id", "summary", "lifecycle")} for p in candidates
                        ],
                        "validation_errors": errors,
                    },
                )
                save(
                    "authorization",
                    {
                        "pass": client.forbidden_attempts == 0
                        and api.app.state.models.forbidden_attempts == 0,
                        "forbidden_attempts": client.forbidden_attempts
                        + api.app.state.models.forbidden_attempts,
                    },
                )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=Path(".dev/live-model.json"))
    args = parser.parse_args()
    run(args.config, args.out)
