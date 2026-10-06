import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from agent_helpers import agent_config, tokens, wiki_client
from conftest import make_page
from fake_llm import FakeLLM
from fastapi.testclient import TestClient

from wikiagent.api import create_app
from wikiagent.chat.loop import Chat
from wikiagent.heal.run import Healer
from wikiagent.heal.scheduler import Scheduler, in_window
from wikiagent.jobs.runner import JobRunner
from wikiagent.models import ModelClient
from wikiagent.state import AgentState
from wikisvc.config import Settings
from wikisvc.domain.markdown import render
from wikisvc.storage.gitrepo import GitRepo
from wikisvc.storage.safefs import SafeFS


def seed_heal(client: TestClient, config: Settings, count: int = 40) -> None:
    rt = client.app.state.runtime
    fs = SafeFS(config.wiki_root)
    source = fs.read("wiki/sources/example-1.md")
    for path in fs.files("wiki/**/*.md"):
        fs.path(path).unlink()
    fs.write("wiki/sources/example-1.md", source)
    problems = json.loads((Path(__file__).parent / "fixtures/heal/problems.json").read_text())
    for n in range(count):
        values = {
            "summary": f"Обрабатывай ошибки операции номер {n} с понятным сообщением.",
            "category": "errors",
            "level": "should",
            "lifecycle": "active",
            "applies_to": ["lang:python"],
            "origin": "team",
            "owner": "team",
            "sources": ["src-example-1"],
            "aliases": [f"операция {n}", f"operation {n}"],
            "enforced_by": ["tool:checks"],
            "status": "verified",
            "verified_by": "alice",
            "verified_at": "2026-10-06",
            "updated": "2026-10-06",
        }
        if n < len(problems):
            values.update(problems[n])
        page = make_page(rt.registry, f"rule-heal-{n:02}", "rule", **values)
        fs.write(page.path, render(page.frontmatter.model_dump(mode="json"), page.body_md))
    GitRepo(config.wiki_root).commit("Seed 40 rules with five problems", "fixtures")
    rt.reindex()


def verdict(task: str, data: dict[str, Any]) -> dict[str, Any]:
    pages = {p["id"]: p for p in data["pages"]}
    pairs = {
        ("rule-heal-00", "rule-heal-01"): ("conflicts", "conflicts_with"),
        ("rule-heal-02", "rule-heal-03"): ("duplicate", "supersedes"),
        ("rule-heal-04", "rule-heal-05"): ("refines", "refines"),
        ("rule-heal-06", "rule-heal-07"): ("scope_mismatch", None),
    }
    ids = tuple(sorted(pages))
    if ids not in pairs:
        return {"relation": "none", "confidence": 0.99, "explanation": "Нет проблемы."}
    relation, rel = pairs[ids]
    fix = (
        {"page": ids[0], "op": "add_relation", "rel": rel, "target": ids[1]}
        if rel
        else {"page": ids[0], "op": "set_field", "field": "applies_to", "value": ["lang:dotnet"]}
    )
    return {
        "relation": relation,
        "confidence": 0.98,
        "explanation": "Подтверждённая проблема " + relation,
        "evidence": [{"page": key, "quote": pages[key]["summary"]} for key in ids],
        "suggested_fix": [fix],
    }


def test_heal_five_problems_cache_changed_and_dismissed(
    client: TestClient, config: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed_heal(client, config)
    agent, human = tokens(client)
    client.headers["Authorization"] = "Bearer " + agent
    monkeypatch.setenv("WIKIAGENT_TOKEN", agent)
    settings = agent_config(tmp_path / "agent")
    settings.heal.max_model_calls_per_run = 2000
    settings.heal.max_model_calls_per_day = 10000
    state = AgentState(settings.state_dir)
    wiki = wiki_client(client, settings)
    fake = FakeLLM(verdict)
    models = ModelClient(settings, state, fake.http)
    chat = Chat(wiki, models, state)
    healer = Healer(wiki, models, state, chat, lambda _: None)
    actor = wiki.check_writer()
    head = GitRepo(config.wiki_root).run("rev-parse", "HEAD")
    job = state.job("heal", actor, {"scope": "full"})
    healer.run(job, {"scope": "full"})
    report = state.restore(job, "report")
    assert not report["discarded"], report
    assert not report["retry_needed"] and not report["budget_exhausted"]
    findings = wiki.all("/findings")
    expected = {
        "conflicts",
        "duplicate",
        "refines",
        "scope_mismatch",
        "lint_W_DEPENDS_ON_DEPRECATED",
    }
    assert expected <= {f["kind"] for f in findings}
    for finding in findings:
        if finding["kind"] in expected:
            proposal = wiki.request("GET", "/proposals/" + finding["proposal_pid"])
            assert proposal["kind"] == "heal" and proposal["status"] == "submitted"
            assert not wiki.request("GET", "/proposals/" + proposal["pid"] + "/validate")["errors"]
    assert any(task == "heal_review" for task, _ in fake.calls)
    assert GitRepo(config.wiki_root).run("rev-parse", "HEAD") == head
    previous_calls = len(fake.calls)
    healer.run(state.job("heal", actor, {}), {"scope": "full"})
    assert len(fake.calls) == previous_calls
    dismissed = next(f for f in findings if f["kind"] == "conflicts")
    assert (
        client.post(
            "/api/v1/findings/" + dismissed["id"] + "/dismiss",
            headers={"Authorization": "Bearer " + human},
            json={"reason": "Допустимое исключение."},
        ).status_code
        == 200
    )
    healer.run(state.job("heal", actor, {}), {})
    assert len(fake.calls) == previous_calls
    assert not [f for f in wiki.all("/findings", status="open") if f["kind"] == "conflicts"]
    fs = SafeFS(config.wiki_root)
    path = "wiki/rules/heal-00.md"
    fs.write(path, fs.read(path) + "\nУточнение для повторной проверки.\n")
    GitRepo(config.wiki_root).commit("Change one rule", "fixtures")
    client.app.state.runtime.reindex()
    healer.run(state.job("heal", actor, {}), {})
    assert len(fake.calls) > previous_calls
    assert all(
        "rule-heal-00" in {p["id"] for p in data["pages"]}
        for _, data in fake.calls[previous_calls:]
    )
    new = [f for f in wiki.all("/findings", status="open") if f["kind"] == "conflicts"]
    assert len(new) == 1 and new[0]["fingerprint"] != dismissed["fingerprint"]
    assert wiki.forbidden_attempts == 0


def test_heal_quote_rejection_and_budget(
    client: TestClient, config: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed_heal(client, config, 2)
    agent, _ = tokens(client)
    monkeypatch.setenv("WIKIAGENT_TOKEN", agent)
    settings = agent_config(tmp_path / "agent")
    state = AgentState(settings.state_dir)
    wiki = wiki_client(client, settings)

    def hallucinate(task: str, data: dict[str, Any]) -> dict[str, Any]:
        result = verdict(task, data)
        result["evidence"][0]["quote"] = "Фраза, которой нигде нет."
        return result

    fake = FakeLLM(hallucinate)
    models = ModelClient(settings, state, fake.http)
    healer = Healer(wiki, models, state, Chat(wiki, models, state), lambda _: None)
    job = state.job("heal", wiki.check_writer(), {})
    settings.heal.max_model_calls_per_run = 1
    healer.run(job, {})
    assert not fake.calls and state.restore(job, "report")["budget_exhausted"]
    settings.heal.max_model_calls_per_run = 20
    healer.run(job, {})
    assert len(fake.calls) == 3
    assert state.restore(job, "report")["discarded"][0]["code"] == "E_MODEL_OUTPUT"
    assert not wiki.all("/findings", kind="conflicts")
    healer.run(job, {})
    assert len(fake.calls) == 3


def test_heal_chat_priority_and_api(
    client: TestClient, config: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed_heal(client, config, 4)
    agent, human = tokens(client)
    monkeypatch.setenv("WIKIAGENT_TOKEN", agent)
    settings = agent_config(tmp_path / "agent")
    state = AgentState(settings.state_dir)
    wiki = wiki_client(client, settings)
    first, release_pair, entered_chat, release_chat = (threading.Event() for _ in range(4))

    def respond(task: str, data: dict[str, Any]) -> dict[str, Any]:
        if task == "route":
            entered_chat.set()
            assert release_chat.wait(15)
            return {"intent": "other", "clarification": "Готово."}
        if not first.is_set():
            first.set()
            assert release_pair.wait(15)
        return {"relation": "none", "confidence": 1, "explanation": "Нет проблемы."}

    fake = FakeLLM(respond)
    models = ModelClient(settings, state, fake.http)
    with (
        TestClient(create_app(settings, wiki, models)) as api,
        ThreadPoolExecutor(max_workers=1) as pool,
    ):
        api.headers["Authorization"] = "Bearer " + human
        session = api.post("/chat/sessions", json={}).json()
        job = api.post("/jobs/heal", json={"scope": "full"})
        assert job.status_code == 202, job.text
        job_id = job.json()["id"]
        try:
            assert first.wait(10)
            assert api.post("/jobs/heal", json={}).status_code == 409
            pending = pool.submit(
                api.post, "/chat/sessions/" + session["id"] + "/messages", json={"text": "Привет"}
            )
            deadline = time.monotonic() + 10
            while not api.app.state.chat.active and time.monotonic() < deadline:
                time.sleep(0.01)
            assert api.app.state.chat.active
            release_pair.set()
            assert entered_chat.wait(10)
            deadline = time.monotonic() + 10
            while (
                api.get("/jobs/" + job_id).json()["status"] != "waiting_chat"
                and time.monotonic() < deadline
            ):
                time.sleep(0.01)
            assert api.get("/jobs/" + job_id).json()["status"] == "waiting_chat"
            assert len([c for c in fake.calls if c[0] == "heal_pair"]) == 1
            release_chat.set()
            assert pending.result(10).status_code == 200
            deadline = time.monotonic() + 10
            while (
                api.get("/jobs/" + job_id).json()["status"] not in ("done", "failed")
                and time.monotonic() < deadline
            ):
                time.sleep(0.01)
            assert api.get("/jobs/" + job_id).json()["status"] == "done"
            assert len([c for c in fake.calls if c[0] == "heal_pair"]) > 1
        finally:
            release_pair.set()
            release_chat.set()
    assert wiki.forbidden_attempts == 0


def test_scheduler_idle_windows_and_full_sweep(
    client: TestClient, config: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed_heal(client, config, 2)
    agent, _ = tokens(client)
    monkeypatch.setenv("WIKIAGENT_TOKEN", agent)
    settings = agent_config(tmp_path / "agent")
    state = AgentState(settings.state_dir)
    wiki = wiki_client(client, settings)
    models = ModelClient(settings, state, FakeLLM(verdict).http)
    runner = JobRunner(state, wiki, models, Chat(wiki, models, state))
    scheduler = Scheduler(runner)
    moment = datetime(2026, 10, 6, 2, tzinfo=UTC)
    scheduler.started = moment - timedelta(hours=1)
    started: list[str] = []
    monkeypatch.setattr(runner, "start", started.append)
    try:
        assert in_window(moment, ["23:00-04:00"])
        assert scheduler.tick(moment.replace(hour=12)) is None
        scheduler.started = moment
        assert scheduler.tick(moment) is None
        scheduler.started -= timedelta(hours=1)
        job = scheduler.tick(moment)
        assert job and started == [job]
        assert state.rows("SELECT payload FROM jobs WHERE id=?", (job,))[0][
            "payload"
        ] == json.dumps({"scope": "full", "scheduled": True})
        assert scheduler.tick(moment) is None
        state.status(job, "done")
        # Simulate a successful full sweep and a subsequent idle interval.
        state.checkpoint("heal", "last_full", moment.isoformat())
        state.checkpoint(
            "heal",
            "hashes",
            {
                p["id"]: p["version"]
                for p in wiki.all("/rules", lifecycle="candidate,active,deprecated")
            },
        )
        with state.connect() as db:
            db.execute("UPDATE jobs SET updated_at=?", ((moment - timedelta(hours=1)).isoformat(),))
        assert scheduler.tick(moment) is None
        state.checkpoint("heal", "hashes", {})
        assert scheduler.tick(moment)
    finally:
        runner.close()
