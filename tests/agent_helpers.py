import json
from pathlib import Path
from typing import Any

import httpx
from conftest import make_page
from fastapi.testclient import TestClient

from wikiagent.client import WikiClient
from wikiagent.config import AgentConfig
from wikisvc.config import Settings
from wikisvc.domain.markdown import render
from wikisvc.services.auth import Auth
from wikisvc.storage.gitrepo import GitRepo
from wikisvc.storage.safefs import SafeFS


def agent_config(path: Path) -> AgentConfig:
    return AgentConfig.model_validate(
        {
            "state_dir": str(path),
            "models": {
                role: {"base_url": "http://models/v1", "model": "fake-" + role}
                for role in ("planner", "reviewer", "chat")
            },
        }
    )


def wiki_client(client: TestClient, config: AgentConfig) -> WikiClient:
    def forward(request: httpx.Request) -> httpx.Response:
        response = client.request(
            request.method, str(request.url), headers=dict(request.headers), content=request.content
        )
        return httpx.Response(
            response.status_code,
            content=response.content,
            headers={"Content-Type": "application/json"},
        )

    return WikiClient(
        config.wikisvc,
        http=httpx.Client(base_url="http://testserver", transport=httpx.MockTransport(forward)),
    )


def seed_chat(client: TestClient, config: Settings) -> None:
    rt = client.app.state.runtime
    fs = SafeFS(config.wiki_root)
    for page_id, summary, level in [
        (
            "rule-http-requests-sync",
            "Используй requests для синхронных HTTP запросов Python.",
            "should",
        ),
        (
            "rule-python-type-hints",
            "Добавляй аннотации типов ко всем публичным функциям Python.",
            "must",
        ),
    ]:
        page = make_page(
            rt.registry,
            page_id,
            "rule",
            title=page_id,
            summary=summary,
            status="verified",
            verified_by="human",
            verified_at="2026-10-02",
            category="stack",
            level=level,
            lifecycle="active",
            applies_to=["lang:python"],
            origin="team",
            owner="team-python",
            sources=["src-example-1"],
            aliases=["сетевые запросы", "HTTP Python"],
        )
        fs.write(page.path, render(page.frontmatter.model_dump(mode="json"), page.body_md))
    pattern = make_page(
        rt.registry,
        "pat-fastapi-sync-endpoint",
        "pattern",
        title="FastAPI sync endpoint",
        summary="Пример синхронного обработчика FastAPI с requests.",
        relations={"governed_by": ["rule-http-requests-sync"]},
    )
    fs.write(pattern.path, render(pattern.frontmatter.model_dump(mode="json"), pattern.body_md))
    GitRepo(config.wiki_root).commit("Seed planner corpus", "fixtures")
    rt.reindex()


def event(response: httpx.Response) -> dict[str, Any]:
    for block in response.text.split("\n\n"):
        if block.startswith("event: message\n"):
            return json.loads(block.split("data: ", 1)[1])
    raise AssertionError(response.text)


def tokens(client: TestClient) -> tuple[str, str]:
    auth = Auth(client.app.state.runtime.state)
    return auth.create("chat-agent", "writer", "restricted", person="chat-agent"), auth.create(
        "alice", "reviewer", "restricted", person="alice", kind="human"
    )
