import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from agent_helpers import agent_config, seed_chat, tokens, wiki_client
from conftest import make_page
from fake_llm import FakeLLM
from fastapi.testclient import TestClient
from test_library_extract import extract, library

from wikiagent.api import create_app
from wikiagent.jobs.ingest_book import IngestBook
from wikiagent.models import ModelClient
from wikiagent.planner.builder import Builder
from wikiagent.state import AgentState
from wikisvc.config import Settings
from wikisvc.domain.markdown import render
from wikisvc.storage.gitrepo import GitRepo
from wikisvc.storage.safefs import SafeFS


def test_book_resume_without_duplicates(
    client: TestClient, config: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed_chat(client, config)
    agent, human = tokens(client)
    client.headers["Authorization"] = "Bearer " + agent
    monkeypatch.setenv("WIKIAGENT_TOKEN", agent)
    rt = client.app.state.runtime
    retired = make_page(
        rt.registry,
        "rule-retired-types",
        "rule",
        summary="Keep type hints on public Python functions.",
        category="code-style",
        level="should",
        lifecycle="deprecated",
        deprecated_reason="Rejected idea",
        applies_to=["lang:python"],
        origin="team",
    )
    SafeFS(config.wiki_root).write(
        retired.path, render(retired.frontmatter.model_dump(mode="json"), retired.body_md)
    )
    collision = make_page(
        rt.registry,
        "rule-architecture-use-structured-logs-for-every-operation",
        "rule",
        summary="Сохраняй историческое правило с отдельным смыслом.",
        category="architecture",
        level="should",
        lifecycle="candidate",
        applies_to=["lang:python"],
        origin="team",
    )
    SafeFS(config.wiki_root).write(
        collision.path, render(collision.frontmatter.model_dump(mode="json"), collision.body_md)
    )
    GitRepo(config.wiki_root).commit("Retired candidate fixture", "fixtures")
    rt.reindex()
    raw = library(
        client,
        "handbook.epub",
        (Path(__file__).parent / "fixtures/books/handbook.epub").read_bytes(),
    )
    extract(client, raw["path"])
    settings = agent_config(tmp_path / "agent")
    state = AgentState(settings.state_dir)
    wiki = wiki_client(client, settings)
    quotes = [
        "Use structured logs for every operation.",
        "Use asynchronous HTTP clients in async handlers.",
        "Keep type hints on public Python functions.",
    ]
    # Distinct strings, so swapped or misplaced examples show in the page body.
    examples = {
        "good_example": 'log.info("order saved", order_id=order.id)',
        "bad_example": 'print("order saved")',
    }

    def respond(task: str, data: dict[str, Any]) -> dict[str, Any]:
        if task == "book_chapter":
            chapter = data["chapter"]["n"]
            return {
                "candidates": [
                    {
                        "title": "Chapter " + str(chapter) + " rule",
                        "thesis": quotes[chapter - 1],
                        "category": "architecture",
                        "applies_to_suggestion": ["lang:python"],
                        "aliases": ["правило книги", "book rule"],
                        "rationale": "The provided chapter describes this practice.",
                        "locator": {"unit": "гл.", "start": chapter},
                        "quote": quotes[chapter - 1],
                        **(examples if chapter == 1 else {}),
                        "relations": [
                            {"rule_id": "rule-http-requests-sync", "type": "conflicts_with"}
                        ]
                        if chapter == 2
                        else [],
                    }
                ],
                "state_summary": "Book concepts so far.",
                "open_references": [],
            }
        if task == "classify":
            if "asynchronous" in data["claim"]["text"]:
                return {
                    "relations": [
                        {
                            "relation": "conflicts_with",
                            "target": "rule-http-requests-sync",
                            "confidence": 0.95,
                            "quote": "Используй requests для синхронных HTTP запросов Python.",
                            "reason": "Async versus synchronous requests.",
                        }
                    ]
                }
            return {
                "relations": [
                    {"relation": "new", "confidence": 0.9, "reason": "New idea from the book."}
                ]
            }
        assert task == "book_review"
        return {
            "merge": [],
            "links": [],
            "key_ideas": [{"id": c["id"], "text": c["summary"]} for c in data["candidates"]],
        }

    fake = FakeLLM(respond)
    models = ModelClient(settings, state, fake.http)
    payload = {"raw_path": raw["path"], "title": "Handbook", "scopes_hint": ["lang:python"]}
    actor = {"name": "alice", "person": "alice", "clearance": "restricted"}
    job_id = state.job("ingest_book", actor, payload)
    book = IngestBook(wiki, models, state)
    put = Builder.put

    def crash(
        self: Builder, pid: str, page_id: str, metadata: dict[str, Any], body: str
    ) -> dict[str, Any]:
        result = put(self, pid, page_id, metadata, body)
        if metadata.get("summary") == quotes[1]:
            raise RuntimeError("Process stopped after chapter 2 write")
        return result

    with monkeypatch.context() as patch:
        patch.setattr(Builder, "put", crash)
        with pytest.raises(RuntimeError):
            book.run(job_id, payload)
    assert state.restore(job_id, "chapter_done") == 1
    book.run(job_id, payload)
    report = state.restore(job_id, "report")
    proposal = client.get("/api/v1/proposals/" + report["proposal"]).json()
    assert proposal["status"] == "submitted" and proposal["kind"] == "book"
    rules = [p for p in proposal["pages"] if p["type"] == "rule"]
    assert len(rules) == 2 and all(
        p["lifecycle"] == "candidate" and p["origin"] == "book" for p in rules
    )
    assert any(p["id"] == collision.id + "-2" for p in rules)
    bodies = {p["summary"]: p["body_md"] for p in rules}
    assert (
        "## Примеры\n\nПримеры предложены моделью, проверьте.\n\n"
        f"Так:\n\n{examples['good_example']}\n\nНе так:\n\n{examples['bad_example']}"
    ) in bodies[quotes[0]]
    # Chapter 2 gives no examples: the section says so, with no empty blocks.
    assert "Примеров нет" in bodies[quotes[1]]
    assert "Так:" not in bodies[quotes[1]] and "Не так:" not in bodies[quotes[1]]
    assert (
        client.get("/api/v1/pages/" + collision.id).json()["summary"]
        == collision.frontmatter.summary
    )
    assert report["conflicts"] and any(e["code"] == "SKIP_DEPRECATED" for e in report["errors"])
    assert client.get(f"/api/v1/proposals/{report['proposal']}/validate").json()["errors"] == []
    assert len([c for c in fake.calls if c[0] == "book_chapter"]) == 3
    assert len(json.dumps(state.restore(job_id, "context"), ensure_ascii=False)) / 2.5 <= 1500
    assert wiki.forbidden_attempts == 0
    config.wikiagent_state_dir = settings.state_dir
    client.headers["Authorization"] = "Bearer " + human
    assert client.get("/api/v1/inbox").json()["jobs"]["unfinished"] == 1


def test_book_job_api_needs_outline_and_resume(
    client: TestClient, config: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    agent, human = tokens(client)
    monkeypatch.setenv("WIKIAGENT_TOKEN", agent)
    client.headers["Authorization"] = "Bearer " + agent
    raw = library(client, "notes.txt", b"Original text without chapter headings.")
    extract(client, raw["path"])
    settings = agent_config(tmp_path / "agent")
    state = AgentState(settings.state_dir)
    wiki = wiki_client(client, settings)
    fake = FakeLLM(
        lambda task, data: {"candidates": [], "state_summary": "Notes.", "open_references": []}
    )
    models = ModelClient(settings, state, fake.http)
    with TestClient(create_app(settings, wiki, models)) as api:
        api.headers["Authorization"] = "Bearer " + human
        response = api.post(
            "/jobs/ingest-book", json={"raw_path": raw["path"], "title": "Some notes"}
        )
        assert response.status_code == 202, response.text
        job_id = response.json()["id"]
        deadline = time.monotonic() + 10
        while (
            time.monotonic() < deadline
            and api.get("/jobs/" + job_id).json()["status"] != "needs_outline"
        ):
            time.sleep(0.02)
        assert api.get("/jobs/" + job_id).json()["status"] == "needs_outline"
        assert (
            client.put(
                "/api/v1/raw/" + raw["path"] + "/outline",
                json={"chapters": [{"n": 1, "title": "Notes", "page_from": 1, "page_to": 1}]},
            ).status_code
            == 200
        )
        assert api.post("/jobs/" + job_id + "/resume").status_code == 200
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and api.get("/jobs/" + job_id).json()["status"] not in (
            "awaiting_review",
            "failed",
        ):
            time.sleep(0.02)
        assert api.get("/jobs/" + job_id).json()["status"] == "awaiting_review"
        assert len(api.get("/jobs").json()["items"]) == 1


class RecordingLLM(FakeLLM):
    """Keeps the whole conversation, so the retry feedback sent to the model is visible."""

    def __init__(self, respond: Callable[[str, dict[str, Any]], dict[str, Any]]) -> None:
        super().__init__(respond)
        self.conversations: list[list[dict[str, Any]]] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.conversations.append(json.loads(request.content)["messages"])
        return super().handle(request)


@pytest.mark.parametrize("bad_end", [1, 9], ids=["reversed-2-1", "beyond-2-9"])
def test_book_bad_chapter_range_is_sent_back_to_model(
    client: TestClient,
    config: Settings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    bad_end: int,
) -> None:
    # Issue #10: a candidate citing "гл. 2-1" or "гл. 2-9" (the book has 3 chapters) must
    # fail the locator check like "стр. 4-3" does, so the model corrects it, instead of
    # the bad range reaching the proposal.
    seed_chat(client, config)
    agent, _ = tokens(client)
    client.headers["Authorization"] = "Bearer " + agent
    monkeypatch.setenv("WIKIAGENT_TOKEN", agent)
    raw = library(
        client,
        "handbook.epub",
        (Path(__file__).parent / "fixtures/books/handbook.epub").read_bytes(),
    )
    extract(client, raw["path"])
    settings = agent_config(tmp_path / "agent")
    state = AgentState(settings.state_dir)
    quote = "Use asynchronous HTTP clients in async handlers."
    attempts: list[dict[str, Any]] = []

    def respond(task: str, data: dict[str, Any]) -> dict[str, Any]:
        if task == "book_chapter":
            if data["chapter"]["n"] != 2:
                return {"candidates": [], "state_summary": "Book.", "open_references": []}
            locator = {"unit": "гл.", "start": 2} | ({} if attempts else {"end": bad_end})
            attempts.append(locator)
            return {
                "candidates": [
                    {
                        "title": "Async HTTP rule",
                        "thesis": quote,
                        "category": "architecture",
                        "applies_to_suggestion": ["lang:python"],
                        "aliases": ["асинхронный HTTP", "async HTTP"],
                        "rationale": "The provided chapter describes this practice.",
                        "locator": locator,
                        "quote": quote,
                    }
                ],
                "state_summary": "Book.",
                "open_references": [],
            }
        if task == "classify":
            return {"relations": [{"relation": "new", "confidence": 0.9, "reason": "New."}]}
        assert task == "book_review"
        return {
            "merge": [],
            "links": [],
            "key_ideas": [{"id": c["id"], "text": c["summary"]} for c in data["candidates"]],
        }

    fake = RecordingLLM(respond)
    models = ModelClient(settings, state, fake.http)
    payload = {"raw_path": raw["path"], "title": "Handbook", "scopes_hint": ["lang:python"]}
    actor = {"name": "alice", "person": "alice", "clearance": "restricted"}
    job_id = state.job("ingest_book", actor, payload)
    IngestBook(wiki_client(client, settings), models, state).run(job_id, payload)

    assert attempts == [{"unit": "гл.", "start": 2, "end": bad_end}, {"unit": "гл.", "start": 2}]
    retries = [m for m in fake.conversations if "book_chapter" in m[0]["content"] and len(m) > 2]
    assert len(retries) == 1 and "Главы отсутствуют." in retries[0][-1]["content"]
    report = state.restore(job_id, "report")
    assert report["errors"] == []
    proposal = client.get("/api/v1/proposals/" + report["proposal"]).json()
    bodies = [p["body_md"] for p in proposal["pages"] if p["type"] == "rule"]
    assert len(bodies) == 1 and f'гл. 2 "{quote}"' in bodies[0]
    assert client.get(f"/api/v1/proposals/{report['proposal']}/validate").json()["errors"] == []
