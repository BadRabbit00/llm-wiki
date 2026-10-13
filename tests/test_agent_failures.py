"""Model failure paths: refusals, repairs and retries in wikiagent (issue #13).

Only the model is fake, and it misbehaves the way a real one does: an answer outside the
checks, an id it was never given, a repair that repairs nothing, a tool call in a
structured task, a second opinion that disagrees. Every fake answer is checked against
the response_format grammar the agent sent, so it cannot take a shape llama.cpp would
forbid. wikisvc, its git wiki and every agent class run for real.
"""

import io
import json
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any, NamedTuple

import httpx
import pytest
from agent_helpers import agent_config, event, seed_chat, tokens, wiki_client
from conftest import make_page
from fake_llm import FakeLLM, Reply, full_claim
from fastapi.testclient import TestClient
from test_agent_heal import seed_heal
from test_library_extract import extract, library

from wikiagent.api import create_app
from wikiagent.chat.loop import Chat
from wikiagent.chat.router import Intent
from wikiagent.client import WikiClient
from wikiagent.config import AgentConfig
from wikiagent.heal.run import Healer
from wikiagent.jobs.ingest_book import IngestBook
from wikiagent.models import SYSTEM, ModelClient
from wikiagent.planner.claims import Claims
from wikiagent.planner.pipeline import Planner
from wikiagent.state import AgentState
from wikisvc.config import Settings
from wikisvc.domain.errors import WikiError
from wikisvc.domain.markdown import render
from wikisvc.storage.gitrepo import GitRepo
from wikisvc.storage.safefs import SafeFS

# The fake's existing callback protocol hands the model's input data over as dict[str, Any].
Data = dict[str, Any]
Respond = Callable[[str, Data], Data | Reply]

NEW = {
    "relations": [
        {
            "relation": "new",
            "target": None,
            "confidence": 1,
            "quote": "",
            "reason": "Нет совпадений.",
        }
    ]
}


class Agent(NamedTuple):
    settings: AgentConfig
    state: AgentState
    wiki: WikiClient
    models: ModelClient
    fake: FakeLLM
    sent: list[str]
    human: str
    token: str


def agent(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    respond: Respond,
    observe: Callable[[httpx.Request], None] | None = None,
) -> Agent:
    token, human = tokens(client)
    monkeypatch.setenv("WIKIAGENT_TOKEN", token)
    settings = agent_config(tmp_path / "agent")
    state = AgentState(settings.state_dir)
    sent: list[str] = []

    def record(request: httpx.Request) -> None:
        sent.append(request.method + " " + request.url.path.removeprefix("/api/v1"))
        if observe is not None:
            observe(request)

    wiki = wiki_client(client, settings, record)
    fake = FakeLLM(respond, check_schema=True)
    models = ModelClient(settings, state, fake.http)
    return Agent(settings, state, wiki, models, fake, sent, human, token)


def error_code(response: httpx.Response) -> str:
    for block in response.text.split("\n\n"):
        if block.startswith("event: error\n"):
            return str(json.loads(block.split("data: ", 1)[1])["error"]["code"])
    raise AssertionError(response.text)


def draft_rules(wiki: WikiClient, pid: str) -> dict[str, Data]:
    pages = wiki.request("GET", "/proposals/" + pid)["pages"]
    return {p["id"]: p for p in pages if p["type"] == "rule"}


def test_fake_model_answers_only_within_grammar(tmp_path: Path) -> None:
    """The check the other tests rely on: a key the strict grammar requires is never absent."""
    config = agent_config(tmp_path)
    answer = {"claims": [full_claim()]}  # no remove_ids: llama.cpp could not emit this
    strict = ModelClient(
        config, AgentState(tmp_path), FakeLLM(lambda t, d: answer, check_schema=True).http
    )
    with pytest.raises(AssertionError, match="remove_ids"):
        strict.structured("planner", "extract_claims", Claims, {"message": "async"})
    loose = ModelClient(config, AgentState(tmp_path), FakeLLM(lambda t, d: answer).http)
    assert loose.structured("planner", "extract_claims", Claims, {"message": "async"}).claims


# А5. Builder.validate: the repair loop after a failed /validate.

GHOST = "[[rule-ghost-link]]"


def repair_case(
    client: TestClient,
    config: Settings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    repair: Callable[[Data], Data],
) -> tuple[Agent, Callable[[], Data]]:
    """The model cites a wiki page that does not exist; only /validate of the draft sees it."""
    seed_chat(client, config)

    def respond(task: str, data: Data) -> Data:
        if task == "extract_claims":
            rationale = "Синхронные операции блокируют обработку, см. " + GHOST + "."
            return {"claims": [full_claim(rationale=rationale)], "remove_ids": []}
        if task == "classify":
            return NEW
        assert task == "repair_validation", task
        assert {e["code"] for e in data["errors"]} == {"E_LINK_UNRESOLVED"}
        return repair(data)

    ag = agent(client, tmp_path, monkeypatch, respond)
    text = "Пиши только асинхронный код Python"

    def run() -> Data:
        plans = Planner(ag.wiki, ag.models).run(
            text, {"id": "repair-test", "owner": "alice", "plan": None}, text
        )
        return dict(plans[0])

    return ag, run


def ghost_page(data: Data) -> Data:
    return dict(next(p for p in data["pages"] if GHOST in p["body_md"]))


def repair(page_id: str, **values: object) -> Data:
    fields = {"title": None, "summary": None, "body_md": None, "aliases": None, "applies_to": None}
    return {"pages": [{"id": page_id, **fields, **values}]}


def test_validation_repair_keeps_fields_the_model_left_out(
    client: TestClient, config: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fixed(data: Data) -> Data:
        page = ghost_page(data)
        body = page["body_md"].replace(GHOST, "rule-ghost-link")
        return repair(page["id"], title="Только асинхронный Python", body_md=body)

    ag, run = repair_case(client, config, tmp_path, monkeypatch, fixed)
    plan = run()
    pid = plan["proposal"]
    assert plan["validation"]["errors"] == []
    page = draft_rules(ag.wiki, pid)["rule-async-only"]
    assert GHOST not in page["body_md"] and "см. rule-ghost-link." in page["body_md"]
    assert page["title"] == "Только асинхронный Python"
    # None in Repair means "leave as is": the planner's values survive the repair.
    assert page["summary"] == full_claim()["thesis"]
    assert page["aliases"] == full_claim()["aliases"]
    assert page["applies_to"] == ["lang:python"]
    assert page["lifecycle"] == "candidate" and page["level"] == "should"
    assert ag.fake.count("repair_validation") == 1
    assert ag.sent.count(f"GET /proposals/{pid}/validate") == 2


def test_validation_repair_of_a_page_outside_the_draft_is_refused(
    client: TestClient, config: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = "rule-http-requests-sync"

    def foreign(data: Data) -> Data:
        return repair(target, body_md="## Правило\n\nПодменённое правило.")

    ag, run = repair_case(client, config, tmp_path, monkeypatch, foreign)
    before = ag.wiki.request("GET", "/pages/" + target)["version"]
    with pytest.raises(WikiError) as error:
        run()
    assert error.value.code == "E_AGENT_REPAIR"
    assert ag.fake.count("repair_validation") == 1
    assert not [s for s in ag.sent if s.endswith("/pages/" + target) and not s.startswith("GET")]
    assert ag.wiki.request("GET", "/pages/" + target)["version"] == before


def test_validation_repair_that_fixes_nothing_stops_after_retries(
    client: TestClient, config: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def useless(data: Data) -> Data:
        page = ghost_page(data)
        return repair(page["id"], body_md=page["body_md"])

    ag, run = repair_case(client, config, tmp_path, monkeypatch, useless)
    with pytest.raises(WikiError) as error:
        run()
    retries = ag.settings.limits.retries
    assert error.value.code == "E_AGENT_VALIDATION"
    assert {d["code"] for d in error.value.details} == {"E_LINK_UNRESOLVED"}
    assert ag.fake.count("repair_validation") == retries - 1
    assert len([s for s in ag.sent if s.endswith("/validate")]) == retries


# Б1, Б2. Book: chapter checks and the second pass.

QUOTES = (
    "Use structured logs for every operation.",
    "Use asynchronous HTTP clients in async handlers.",
    "Keep type hints on public Python functions.",
)
EMPTY_REVIEW: Data = {"merge": [], "links": [], "key_ideas": []}


def candidate(n: int, **values: object) -> dict[str, object]:
    return {
        "title": f"Правило главы {n}",
        "thesis": QUOTES[n - 1],
        "category": "architecture",
        "applies_to_suggestion": ["lang:python"],
        "level_suggestion": "should",
        "rationale": "Глава описывает эту практику.",
        "locator": {"unit": "гл.", "start": n, "end": None},
        "quote": QUOTES[n - 1],
        "aliases": ["правило книги", "book rule"],
        "good_example": "",
        "bad_example": "",
        "relations": [],
        **values,
    }


def chapter(*candidates: dict[str, object]) -> Data:
    return {"candidates": list(candidates), "state_summary": "Идеи книги.", "open_references": []}


class Book(NamedTuple):
    ingest: IngestBook
    job: str
    payload: dict[str, str]
    agent: Agent

    def run(self) -> None:
        self.ingest.run(self.job, self.payload)

    def pid(self) -> str:
        return str(self.agent.state.restore(self.job, "proposal"))

    def rules(self) -> dict[str, Data]:
        """Draft rules by thesis: page IDs are allocated by the job, theses are ours."""
        return {p["summary"]: p for p in draft_rules(self.agent.wiki, self.pid()).values()}


def book(
    client: TestClient,
    config: Settings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    respond: Respond,
    observe: Callable[[httpx.Request], None] | None = None,
    data: bytes | None = None,
) -> Book:
    seed_chat(client, config)
    ag = agent(client, tmp_path, monkeypatch, respond, observe)
    # Raw uploads need restricted clearance; the default test token is only internal.
    client.headers["Authorization"] = "Bearer " + ag.token
    if data is None:
        data = (Path(__file__).parent / "fixtures/books/handbook.epub").read_bytes()
    raw = library(client, "handbook.epub", data)
    extract(client, raw["path"])
    payload = {"raw_path": raw["path"], "title": "Handbook"}
    actor = {"name": "alice", "person": "alice", "clearance": "restricted"}
    job = ag.state.job("ingest_book", actor, payload)
    return Book(IngestBook(ag.wiki, ag.models, ag.state), job, payload, ag)


def review_ids(data: Data) -> tuple[str, str, str]:
    ids = {c["summary"]: c["id"] for c in data["candidates"]}
    return ids[QUOTES[0]], ids[QUOTES[1]], ids[QUOTES[2]]


@pytest.mark.parametrize("restart", [False, True], ids=["one-run", "restart-before-link"])
def test_book_review_merge_redirects_links_to_the_survivor(
    client: TestClient,
    config: Settings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    restart: bool,
) -> None:
    crashed: list[str] = []

    def crash(request: httpx.Request) -> None:
        if restart and not crashed and b"add_relation" in request.content:
            crashed.append(request.url.path)
            raise RuntimeError("Process stopped after the merge, before the link")

    def respond(task: str, data: Data) -> Data:
        if task == "book_chapter":
            return chapter(candidate(data["chapter"]["n"]))
        if task == "classify":
            return NEW
        assert task == "book_review", task
        keep, drop, third = review_ids(data)
        # One answer merges a candidate away and links the third one to it.
        return {
            "merge": [{"keep": keep, "drop": drop}],
            "links": [{"src": third, "target": drop, "rel": "refines"}],
            "key_ideas": [],
        }

    job = book(client, config, tmp_path, monkeypatch, respond, crash)
    if restart:
        with pytest.raises(RuntimeError):
            job.run()
    job.run()
    assert len(crashed) == int(restart)
    rules = job.rules()
    assert set(rules) == {QUOTES[0], QUOTES[2]}
    keep, third = rules[QUOTES[0]], rules[QUOTES[2]]
    drop = review_ids(next(d for task, d in job.agent.fake.calls if task == "book_review"))[1]
    # The survivor carries the duplicate's evidence, with its headings demoted.
    assert keep["body_md"].count("Объединён кандидат " + drop) == 1
    assert f'гл. 2 "{QUOTES[1]}"' in keep["body_md"] and "**Правило**" in keep["body_md"]
    assert third["relations"] == {"refines": [keep["id"]]}
    assert f"DELETE /proposals/{job.pid()}/pages/{drop}" in job.agent.sent
    assert job.agent.fake.count("book_review") == 1
    pid = job.pid()
    assert job.agent.wiki.request("GET", "/proposals/" + pid)["status"] == "submitted"
    assert job.agent.wiki.request("GET", f"/proposals/{pid}/validate")["errors"] == []
    assert job.agent.state.restore(job.job, "report")["candidates"] == 2


def test_book_review_merge_into_itself_changes_nothing(
    client: TestClient, config: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def respond(task: str, data: Data) -> Data:
        if task == "book_chapter":
            return chapter(candidate(data["chapter"]["n"]))
        if task == "classify":
            return NEW
        assert task == "book_review", task
        keep = review_ids(data)[0]
        return {**EMPTY_REVIEW, "merge": [{"keep": keep, "drop": keep}]}

    job = book(client, config, tmp_path, monkeypatch, respond)
    job.run()
    rules = job.rules()
    assert set(rules) == set(QUOTES)
    assert "Объединён кандидат" not in rules[QUOTES[0]]["body_md"]
    assert not [s for s in job.agent.sent if s.startswith("DELETE")]
    assert job.agent.wiki.request("GET", "/proposals/" + job.pid())["status"] == "submitted"


@pytest.mark.parametrize("named_as_merged", [False, True], ids=["link", "link-and-merge"])
def test_book_review_link_to_unknown_id_fails_the_job(
    client: TestClient,
    config: Settings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    named_as_merged: bool,
) -> None:
    def respond(task: str, data: Data) -> Data:
        if task == "book_chapter":
            return chapter(candidate(data["chapter"]["n"]))
        if task == "classify":
            return NEW
        assert task == "book_review", task
        src, other, _ = review_ids(data)
        # Naming the invented ID as a merged duplicate must not make it resolvable.
        merge = [{"keep": other, "drop": "rule-made-up"}] if named_as_merged else []
        link = {"src": src, "target": "rule-made-up", "rel": "refines"}
        return {**EMPTY_REVIEW, "merge": merge, "links": [link]}

    job = book(client, config, tmp_path, monkeypatch, respond)
    with pytest.raises(WikiError) as error:
        job.run()
    assert error.value.code == "E_LINK_UNRESOLVED"
    rules = job.rules()
    assert rules[QUOTES[0]]["relations"] == {}
    assert not [s for s in job.agent.sent if s.startswith("PATCH")]
    assert job.agent.wiki.request("GET", "/proposals/" + job.pid())["status"] == "draft"


def test_book_merge_resumed_after_crash_appends_evidence_once(
    client: TestClient, config: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    crashed: list[str] = []

    def crash(request: httpx.Request) -> None:
        if request.method == "DELETE" and not crashed:
            crashed.append(request.url.path)
            raise RuntimeError("Process stopped before the duplicate was removed")

    def respond(task: str, data: Data) -> Data:
        if task == "book_chapter":
            return chapter(candidate(data["chapter"]["n"]))
        if task == "classify":
            return NEW
        assert task == "book_review", task
        keep, drop, _ = review_ids(data)
        return {**EMPTY_REVIEW, "merge": [{"keep": keep, "drop": drop}]}

    job = book(client, config, tmp_path, monkeypatch, respond, crash)
    with pytest.raises(RuntimeError):
        job.run()
    job.run()
    rules = job.rules()
    assert set(rules) == {QUOTES[0], QUOTES[2]} and len(crashed) == 1
    assert rules[QUOTES[0]]["body_md"].count("Объединён кандидат ") == 1
    assert job.agent.fake.count("book_review") == 1
    assert job.agent.wiki.request("GET", "/proposals/" + job.pid())["status"] == "submitted"


FAULTS: dict[str, tuple[dict[str, object], str]] = {
    "scope": ({"applies_to_suggestion": ["lang:cobol"]}, "Область отсутствует в словаре."),
    "link": (
        {"relations": [{"rule_id": "rule-made-up", "type": "refines"}]},
        "Связь отсутствует в полученном контексте.",
    ),
    "locator": ({"locator": {"unit": "стр.", "start": 999, "end": None}}, "Страницы отсутствуют."),
    "quote": (
        {"quote": "Выдуманная фраза, которой нет в главе."},
        "Цитата отсутствует на указанных страницах.",
    ),
}


@pytest.mark.parametrize("fault", list(FAULTS))
def test_book_chapter_check_sends_the_model_back_to_its_mistake(
    client: TestClient,
    config: Settings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    wrong, message = FAULTS[fault]
    attempts: dict[int, int] = {}

    def respond(task: str, data: Data) -> Data:
        if task == "book_chapter":
            n = data["chapter"]["n"]
            attempts[n] = attempts.get(n, 0) + 1
            return chapter(candidate(n, **(wrong if (n, attempts[n]) == (1, 1) else {})))
        if task == "classify":
            return NEW
        assert task == "book_review", task
        return EMPTY_REVIEW

    job = book(client, config, tmp_path, monkeypatch, respond)
    job.run()
    assert attempts == {1: 2, 2: 1, 3: 1}
    retry = [
        r
        for r, (task, data) in zip(job.agent.fake.requests, job.agent.fake.calls, strict=True)
        if task == "book_chapter" and data["chapter"]["n"] == 1
    ][1]
    assert message in retry["messages"][-1]["content"]
    assert set(job.rules()) == set(QUOTES)
    assert job.rules()[QUOTES[0]]["applies_to"] == ["lang:python"]
    assert job.agent.state.restore(job.job, "report")["errors"] == []


def test_book_chapter_errors_and_duplicates_are_reported_not_written(
    client: TestClient, config: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    duplicate = "rule-python-type-hints"

    def respond(task: str, data: Data) -> Data:
        if task == "book_chapter":
            n = data["chapter"]["n"]
            # Chapter 2: the model insists on a quote the chapter does not contain.
            return chapter(candidate(n, **({"quote": "Цитата, которой нет."} if n == 2 else {})))
        if task == "classify":
            if data["claim"]["text"] != QUOTES[2]:
                return NEW
            pages = {p["id"]: p for p in data["pages"]}
            return {
                "relations": [
                    {
                        "relation": "duplicate_of",
                        "target": duplicate,
                        "confidence": 0.95,
                        "quote": pages[duplicate]["summary"],
                        "reason": "Это правило про аннотации типов уже есть.",
                    }
                ]
            }
        assert task == "book_review", task
        return EMPTY_REVIEW

    job = book(client, config, tmp_path, monkeypatch, respond)
    job.run()
    report = job.agent.state.restore(job.job, "report")
    assert report["errors"] == [
        {"chapter": 2, "code": "E_MODEL_OUTPUT"},
        {"chapter": 3, "code": "SKIP_DUPLICATE", "thesis": QUOTES[2]},
    ]
    assert set(job.rules()) == {QUOTES[0]} and report["candidates"] == 1
    chapters = [d["chapter"]["n"] for t, d in job.agent.fake.calls if t == "book_chapter"]
    assert chapters == [1, *[2] * job.agent.settings.limits.retries, 3]
    assert job.agent.wiki.request("GET", "/proposals/" + job.pid())["status"] == "submitted"


# Б3, Б4. Healer.

HEAL_PAIR = ["rule-heal-00", "rule-heal-01"]


def healer(ag: Agent) -> Healer:
    return Healer(ag.wiki, ag.models, ag.state, Chat(ag.wiki, ag.models, ag.state), lambda _: None)


def heal(ag: Agent, instance: Healer) -> tuple[str, Data]:
    job = ag.state.job("heal", ag.wiki.check_writer(), {})
    instance.run(job, {})
    status = ag.state.rows("SELECT status FROM jobs WHERE id=?", (job,))[0]["status"]
    return str(status), dict(ag.state.restore(job, "report"))


def evidence(data: Data) -> list[dict[str, str]]:
    return [{"page": p["id"], "quote": p["summary"]} for p in data["pages"]]


def pair_checks(ag: Agent) -> list[Data]:
    return ag.state.rows("SELECT a_id, b_id, verdict, confidence FROM pair_checks")


def touch(client: TestClient, config: Settings, page_id: str) -> None:
    """A person edits the rule on main while the healer is working."""
    fs = SafeFS(config.wiki_root)
    path = "wiki/rules/" + page_id.removeprefix("rule-") + ".md"
    fs.write(path, fs.read(path) + "\nУточнение человека.\n")
    GitRepo(config.wiki_root).commit("Concurrent edit", "alice")
    client.app.state.runtime.reindex()


@pytest.mark.parametrize(
    "second",
    [
        {"relation": "none", "confidence": 0.95, "explanation": "Правила совместимы."},
        {"relation": "conflicts", "confidence": 0.5, "explanation": "Возможно, конфликт."},
    ],
    ids=["none", "low-confidence"],
)
def test_heal_second_opinion_overrules_must_conflict(
    client: TestClient,
    config: Settings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    second: Data,
) -> None:
    seed_heal(client, config, 2)

    def respond(task: str, data: Data) -> Data:
        if task == "heal_pair":
            return {
                "relation": "conflicts",
                "confidence": 0.98,
                "explanation": "Синхронный и асинхронный клиент несовместимы.",
                "evidence": evidence(data),
                "suggested_fix": [],
            }
        assert task == "heal_review" and data["first_verdict"]["relation"] == "conflicts"
        quotes = evidence(data) if second["relation"] != "none" else []
        return {**second, "evidence": quotes, "suggested_fix": []}

    ag = agent(client, tmp_path, monkeypatch, respond)
    instance = healer(ag)
    status, report = heal(ag, instance)
    assert status == "done" and not report["retry_needed"]
    assert ag.fake.count("heal_pair") == 1 and ag.fake.count("heal_review") == 1
    assert not ag.wiki.all("/findings", kind="conflicts")
    [check] = pair_checks(ag)
    assert [check["a_id"], check["b_id"]] == HEAL_PAIR
    verdict = json.loads(check["verdict"])
    assert verdict["relation"] == "none" and check["confidence"] == second["confidence"]
    assert verdict["explanation"] == "Второе мнение не подтвердило конфликт."
    heal(ag, instance)
    assert ag.fake.count("heal_pair") == 1


def test_heal_deterministic_findings_need_no_model(
    client: TestClient, config: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed_heal(client, config, 2)
    rt = client.app.state.runtime
    fs = SafeFS(config.wiki_root)
    stale = make_page(
        rt.registry,
        "rule-heal-stale",
        "rule",
        summary="Проверяй старые кандидаты правил раз в квартал.",
        category="testing",
        level="should",
        lifecycle="candidate",
        applies_to=["lang:python"],
        origin="team",
        aliases=["старый кандидат", "stale candidate"],
        created="2020-01-01",
        updated="2020-01-01",
    )
    fs.write(stale.path, render(stale.frontmatter.model_dump(mode="json"), stale.body_md))
    fs.write(
        "schema/profiles/tiny.yaml",
        'id: tiny\ntitle: Крошечный бюджет\nscopes: ["lang:python"]\nbudget_tokens: 1\n',
    )
    GitRepo(config.wiki_root).commit("Stale candidate and a tight profile", "fixtures")
    rt.reindex()

    def respond(task: str, data: Data) -> Data:
        assert task == "heal_pair", task
        return {
            "relation": "none",
            "confidence": 0.99,
            "explanation": "Нет проблемы.",
            "evidence": [],
            "suggested_fix": [],
        }

    ag = agent(client, tmp_path, monkeypatch, respond)
    ag.settings.heal.max_findings_per_run = 100
    # Usage counters arrive through the API, as from IDE agents.
    params = {"profile": "python-fastapi", "enforced": "all"}
    compiled = client.get("/api/v1/policies/compile", params=params)
    assert {"rule-heal-00", "rule-heal-01"} <= {p["id"] for p in compiled.json()["included"]}
    ag.wiki.request("GET", "/pages/rule-heal-00")
    items = [{"rule_id": "rule-heal-00", "note": "Нарушено в обработчике."}] * 3 + [
        {"rule_id": "rule-heal-01", "note": "Нарушено в обработчике."}
    ] * 2
    assert client.post("/api/v1/rules/violations", json={"items": items}).status_code == 200
    status, report = heal(ag, healer(ag))
    assert status == "done" and not report["budget_exhausted"] and not report["retry_needed"]
    findings = {(f["kind"], tuple(f["pages"])) for f in ag.wiki.all("/findings")}
    assert {
        ("lint_W_CANDIDATE_STALE", ("rule-heal-stale",)),
        ("lint_W_RULE_UNUSED", ("rule-heal-01",)),
        ("lint_W_RULE_VIOLATED", ("rule-heal-00",)),
        ("lint_W_PROFILE_OVER_BUDGET", ("rule-heal-00",)),
        ("coverage_errors", ("rule-heal-00",)),
    } <= findings
    # An opened rule is in use; two violations are not yet a pattern; active is not stale.
    assert ("lint_W_RULE_UNUSED", ("rule-heal-00",)) not in findings
    assert ("lint_W_RULE_VIOLATED", ("rule-heal-01",)) not in findings
    assert not [f for f in findings if f[0] == "lint_W_CANDIDATE_STALE" and f[1] != (stale.id,)]
    assert {task for task, _ in ag.fake.calls} == {"heal_pair"}


def test_heal_page_changed_before_check_is_retried_next_run(
    client: TestClient, config: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed_heal(client, config, 2)
    edited: list[str] = []

    def edit_once(request: httpx.Request) -> None:
        if request.url.path.endswith("/search") and not edited:
            edited.append("rule-heal-01")
            touch(client, config, "rule-heal-01")

    def respond(task: str, data: Data) -> Data:
        assert task == "heal_pair", task
        return {
            "relation": "none",
            "confidence": 0.99,
            "explanation": "Нет проблемы.",
            "evidence": [],
            "suggested_fix": [],
        }

    ag = agent(client, tmp_path, monkeypatch, respond, edit_once)
    instance = healer(ag)
    status, report = heal(ag, instance)
    assert edited and status == "paused" and report["retry_needed"]
    assert ag.fake.count("heal_pair") == 0 and not pair_checks(ag)
    assert not ag.state.restore("heal", "hashes")
    status, report = heal(ag, instance)
    assert status == "done" and not report["retry_needed"]
    assert ag.fake.count("heal_pair") == 1 and len(pair_checks(ag)) == 1


def test_heal_page_changed_during_check_is_not_cached(
    client: TestClient, config: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed_heal(client, config, 2)

    def respond(task: str, data: Data) -> Data:
        assert task == "heal_pair", task
        if ag.fake.count("heal_pair") == 1:
            touch(client, config, "rule-heal-01")
        return {
            "relation": "duplicate",
            "confidence": 0.95,
            "explanation": "Правила об одном и том же.",
            "evidence": evidence(data),
            "suggested_fix": [],
        }

    ag = agent(client, tmp_path, monkeypatch, respond)
    instance = healer(ag)
    status, report = heal(ag, instance)
    assert status == "paused" and report["retry_needed"] and not report["discarded"]
    assert not ag.wiki.all("/findings", kind="duplicate") and not pair_checks(ag)
    status, report = heal(ag, instance)
    assert status == "done" and not report["retry_needed"]
    assert ag.fake.count("heal_pair") == 2
    [finding] = ag.wiki.all("/findings", kind="duplicate")
    assert finding["pages"] == HEAL_PAIR


def test_heal_wiki_refusal_is_retried_not_cached(
    client: TestClient, config: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed_heal(client, config, 2)
    scope = ["lang:cobol"]

    def respond(task: str, data: Data) -> Data:
        assert task == "heal_pair", task
        fix = {"page": HEAL_PAIR[1], "op": "set_field", "field": "applies_to", "value": scope}
        return {
            "relation": "scope_mismatch",
            "confidence": 0.9,
            "explanation": "Области правил расходятся.",
            "evidence": evidence(data),
            "suggested_fix": [{"rel": None, "target": None, "heading": None, "text": None, **fix}],
        }

    ag = agent(client, tmp_path, monkeypatch, respond)
    instance = healer(ag)
    status, report = heal(ag, instance)
    # wikisvc refuses the fix: not a model format error, so the pair is not cached as none.
    assert report["discarded"] == [{"pair": HEAL_PAIR, "code": "E_SCOPE_UNKNOWN"}]
    assert status == "paused" and report["retry_needed"]
    assert not pair_checks(ag) and not ag.state.restore("heal", "hashes")
    scope[:] = ["lang:python", "app:cli"]
    status, report = heal(ag, instance)
    assert status == "done" and not report["discarded"] and ag.fake.count("heal_pair") == 2
    [finding] = ag.wiki.all("/findings", kind="scope_mismatch")
    proposal = ag.wiki.request("GET", "/proposals/" + finding["proposal_pid"])
    assert proposal["status"] == "submitted"


# Б5, Б6. Planner: double confirmation, plan split, withdrawal guard.


def many(count: int) -> list[dict[str, object]]:
    return [
        full_claim(
            f"rule-split-{n:02}",
            text=f"Правило разбиения номер {n}",
            title=f"Правило разбиения {n}",
            thesis=f"Соблюдай правило разбиения номер {n} в коде Python.",
        )
        for n in range(1, count + 1)
    ]


TYPE_HINTS = full_claim(
    "rule-type-hints-private",
    text="Аннотации типов нужны и закрытым функциям Python",
    title="Аннотации закрытых функций",
    thesis="Добавляй аннотации типов и к закрытым функциям Python.",
    aliases=["аннотации типов", "type hints"],
)


@pytest.mark.parametrize(
    ("claims", "refines_must", "expected"),
    [
        ([full_claim()], False, False),
        ([full_claim(level_guess="must")], False, True),
        ([TYPE_HINTS], True, True),
        (many(5), False, False),
        (many(6), False, True),
    ],
    ids=["should", "must", "touches-must", "five-targets", "six-targets"],
)
def test_plan_needs_double_confirm(
    client: TestClient,
    config: Settings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    claims: list[dict[str, object]],
    refines_must: bool,
    expected: bool,
) -> None:
    seed_chat(client, config)
    must = "rule-python-type-hints"

    def respond(task: str, data: Data) -> Data:
        if task == "extract_claims":
            return {"claims": claims, "remove_ids": []}
        assert task == "classify", task
        if not refines_must:
            return NEW
        pages = {p["id"]: p for p in data["pages"]}
        assert pages[must]["level"] == "must"
        return {
            "relations": [
                {
                    "relation": "refines",
                    "target": must,
                    "confidence": 0.9,
                    "quote": pages[must]["summary"],
                    "reason": "Уточняет обязательное правило.",
                }
            ]
        }

    ag = agent(client, tmp_path, monkeypatch, respond)
    text = "Новые правила кода"
    plan = Planner(ag.wiki, ag.models).run(
        text, {"id": "confirm-test", "owner": "alice", "plan": None}, text
    )[0]
    assert len(plan["items"]) == len(claims)
    assert plan["needs_double_confirm"] is expected
    # The UI reads the flag from the proposal notes, not from the chat reply.
    notes = ag.wiki.request("GET", "/proposals/" + plan["proposal"])["notes"]
    assert notes["needs_double_confirm"] is expected


def test_plan_over_ten_items_splits_into_a_new_proposal(
    client: TestClient, config: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed_chat(client, config)
    batch = many(12)
    ids = [str(c["id"]) for c in batch]

    def respond(task: str, data: Data) -> Data:
        if task == "extract_claims":
            claims = [full_claim()] if data["message"] == "первое" else batch
            return {"claims": claims, "remove_ids": []}
        assert task == "classify", task
        return NEW

    ag = agent(client, tmp_path, monkeypatch, respond)
    planner = Planner(ag.wiki, ag.models)
    session: Data = {"id": "split-test", "owner": "alice", "plan": None}
    first = planner.run("первое", session, "первое")[0]
    plans = planner.run("пакет", {**session, "plan": first}, "первое\n\nпакет")
    assert len(plans) == 2
    head, tail = plans
    # The reply fills the session's draft; the overflow gets a draft of its own.
    assert head["proposal"] == first["proposal"] != tail["proposal"]
    assert [i["target"] for i in head["items"]] == ids[:10]
    assert [i["target"] for i in tail["items"]] == ids[10:]
    assert [i["n"] for i in tail["items"]] == [1, 2]
    assert [p["id"] for p in head["accept_body"]["promote"]] == ["rule-async-only", *ids[:10]]
    assert [p["id"] for p in tail["accept_body"]["promote"]] == ids[10:]
    assert set(draft_rules(ag.wiki, head["proposal"])) == {"rule-async-only", *ids[:10]}
    assert set(draft_rules(ag.wiki, tail["proposal"])) == set(ids[10:])
    notes = ag.wiki.request("GET", "/proposals/" + tail["proposal"])["notes"]
    assert [p["id"] for p in notes["accept_body"]["promote"]] == ids[10:]


def test_withdrawal_of_a_page_outside_the_plan_is_refused(
    client: TestClient, config: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed_chat(client, config)
    foreign = "rule-http-requests-sync"

    def respond(task: str, data: Data) -> Data:
        if task == "extract_claims":
            if data["message"] == "убери":
                return {"claims": [], "remove_ids": ["rule-async-only", foreign]}
            return {"claims": [full_claim()], "remove_ids": []}
        assert task == "classify", task
        return NEW

    ag = agent(client, tmp_path, monkeypatch, respond)
    planner = Planner(ag.wiki, ag.models)
    session: Data = {"id": "remove-test", "owner": "alice", "plan": None}
    first = planner.run("правило", session, "правило")[0]
    pid = first["proposal"]
    before = {p["id"]: p["version"] for p in ag.wiki.request("GET", "/proposals/" + pid)["pages"]}
    with pytest.raises(WikiError) as error:
        planner.run("убери", {**session, "plan": first}, "правило\n\nубери")
    assert error.value.code == "E_AGENT_REPAIR"
    assert not [s for s in ag.sent if s.startswith("DELETE")]
    after = {p["id"]: p["version"] for p in ag.wiki.request("GET", "/proposals/" + pid)["pages"]}
    assert after == before and "rule-async-only" in after
    assert [p["id"] for p in first["accept_body"]["promote"]] == ["rule-async-only"]
    assert ag.fake.count("extract_claims") == 2


# Б7, Б8. Chat: question mode with tools, actions on an accepted proposal.


def tool_call(call_id: str, name: str, arguments: dict[str, object]) -> dict[str, object]:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments)},
    }


def test_question_runs_read_tools_and_refuses_writes(
    client: TestClient, config: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed_chat(client, config)
    answer = "Правило rule-http-requests-sync велит использовать requests."

    def respond(task: str, data: Data) -> Data | Reply:
        if task == "route":
            return {"intent": "question", "clarification": None}
        assert task == SYSTEM, task
        if ag.fake.count(SYSTEM) > 1:
            return Reply(content=answer)
        write = {"pid": "abcdef", "id": "rule-x", "frontmatter": {}, "body_md": ""}
        return Reply(
            tool_calls=[
                tool_call("call-1", "put_page", write),
                tool_call("call-2", "get_rule", {"id": "rule-http-requests-sync"}),
            ]
        )

    ag = agent(client, tmp_path, monkeypatch, respond)
    with TestClient(create_app(ag.settings, ag.wiki, ag.models)) as chat:
        chat.headers["Authorization"] = "Bearer " + ag.human
        sid = chat.post("/chat/sessions", json={}).json()["id"]
        result = event(chat.post(f"/chat/sessions/{sid}/messages", json={"text": "Что с HTTP?"}))
    assert result == {"text": answer}
    assert ag.fake.count(SYSTEM) == 2
    forbidden, read = [m for m in ag.fake.requests[-1]["messages"] if m["role"] == "tool"]
    assert forbidden["tool_call_id"] == "call-1"
    assert json.loads(forbidden["content"])["error"]["code"] == "E_AGENT_TOOL_FORBIDDEN"
    assert read["tool_call_id"] == "call-2"
    assert "Используй requests для синхронных HTTP запросов Python." in read["content"]
    assert ag.wiki.forbidden_attempts == 1
    assert not [s for s in ag.sent if s.startswith(("PUT", "PATCH", "DELETE"))]


@pytest.mark.parametrize(("per_reply", "replies"), [(1, 3), (4, 1)], ids=["loop", "burst"])
def test_question_tool_loop_stops_at_step_limit(
    client: TestClient,
    config: Settings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    per_reply: int,
    replies: int,
) -> None:
    seed_chat(client, config)

    def respond(task: str, data: Data) -> Data | Reply:
        if task == "route":
            return {"intent": "question", "clarification": None}
        assert task == SYSTEM, task
        rule = {"id": "rule-http-requests-sync"}
        return Reply(tool_calls=[tool_call(f"c{n}", "get_rule", rule) for n in range(per_reply)])

    ag = agent(client, tmp_path, monkeypatch, respond)
    ag.settings.limits.max_tool_steps = 3
    with TestClient(create_app(ag.settings, ag.wiki, ag.models)) as chat:
        chat.headers["Authorization"] = "Bearer " + ag.human
        sid = chat.post("/chat/sessions", json={}).json()["id"]
        response = chat.post(f"/chat/sessions/{sid}/messages", json={"text": "Что с HTTP?"})
    assert error_code(response) == "E_AGENT_STEP_LIMIT"
    assert ag.fake.count(SYSTEM) == replies
    assert ag.sent.count("GET /rules/rule-http-requests-sync") == 3


def test_cancel_or_revert_of_accepted_proposal_is_left_to_a_person(
    client: TestClient, config: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed_chat(client, config)

    def respond(task: str, data: Data) -> Data:
        if task == "route":
            intent = {"отмени": "cancel", "откати": "revert"}[data["message"]]
            return {"intent": intent, "clarification": None}
        if task == "extract_claims":
            return {"claims": [full_claim()], "remove_ids": []}
        assert task == "classify", task
        return NEW

    ag = agent(client, tmp_path, monkeypatch, respond)
    text = "Пиши только асинхронный код Python"
    plan = Planner(ag.wiki, ag.models).run(
        text, {"id": "accepted-test", "owner": "alice", "plan": None}, text
    )[0]
    pid = plan["proposal"]
    human = {"Authorization": "Bearer " + ag.human}
    accepted = client.post(
        f"/api/v1/proposals/{pid}/accept", headers=human, json=plan["accept_body"]
    )
    assert accepted.status_code == 200, accepted.text
    action = {"method": "POST", "path": f"/api/v1/proposals/{pid}/revert"}
    with TestClient(create_app(ag.settings, ag.wiki, ag.models)) as chat:
        chat.headers["Authorization"] = "Bearer " + ag.human
        sid = chat.post("/chat/sessions", json={}).json()["id"]
        chat.app.state.chat.sessions.message(sid, "assistant", "Предложение принято", plan)
        ag.sent.clear()
        cancel = event(chat.post(f"/chat/sessions/{sid}/messages", json={"text": "отмени"}))
        revert = event(chat.post(f"/chat/sessions/{sid}/messages", json={"text": "откати"}))
        session = chat.get(f"/chat/sessions/{sid}").json()
    assert cancel == {"text": "Для отката нужно подтверждение человека.", "human_action": action}
    assert revert == {"text": "Откат подтверждает человек.", "human_action": action}
    assert client.get(f"/api/v1/proposals/{pid}", headers=human).json()["status"] == "accepted"
    assert not [s for s in ag.sent if not s.startswith("GET")]
    assert "cancelled" not in session["plan"] and ag.wiki.forbidden_attempts == 0


def test_tool_calls_in_structured_answer_are_refused_and_retried(
    client: TestClient, config: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    answer = {"intent": "other", "clarification": "Какое правило нужно оформить?"}

    def respond(task: str, data: Data) -> Data | Reply:
        assert task == "route", task
        if ag.fake.count("route") == 1:
            # Valid JSON beside a tool call: the tool call alone makes it unacceptable.
            return Reply(
                content=json.dumps(answer, ensure_ascii=False),
                tool_calls=[tool_call("call-1", "put_page", {})],
            )
        return answer

    ag = agent(client, tmp_path, monkeypatch, respond)
    with TestClient(create_app(ag.settings, ag.wiki, ag.models)) as chat:
        chat.headers["Authorization"] = "Bearer " + ag.human
        sid = chat.post("/chat/sessions", json={}).json()["id"]
        result = event(chat.post(f"/chat/sessions/{sid}/messages", json={"text": "Привет"}))
    assert result == {"text": "Какое правило нужно оформить?"}
    assert ag.fake.count("route") == 2 and ag.models.forbidden_attempts == 1
    assert "Tools are forbidden" in ag.fake.requests[1]["messages"][-1]["content"]
    # The structured path never executes a tool, so the wiki saw no attempt at all.
    assert ag.wiki.forbidden_attempts == 0
    assert not [s for s in ag.sent if not s.startswith("GET")]


# A model that is down is not a model that answered badly: nothing is kept as checked.

DOWN = Reply(status=503)


@pytest.mark.parametrize(
    ("script", "code"),
    [
        (["down", "down", "down"], "E_MODEL_UNAVAILABLE"),
        (["down", "garbled", "down"], "E_MODEL_OUTPUT"),
        (["garbled", "down", "down"], "E_MODEL_OUTPUT"),
    ],
    ids=["never-answered", "answered-once", "answered-first"],
)
def test_structured_reports_an_unreachable_model_as_unavailable(
    tmp_path: Path, script: list[str], code: str
) -> None:
    replies = iter(script)

    def respond(task: str, data: Data) -> Reply:
        # Truncated JSON is what a model cut off by max_tokens actually sends.
        return DOWN if next(replies) == "down" else Reply(content='{"intent": "intake"')

    fake = FakeLLM(respond, check_schema=True)
    model = ModelClient(agent_config(tmp_path), AgentState(tmp_path), fake.http)
    with pytest.raises(WikiError) as error:
        model.structured("chat", "route", Intent, {"message": "Привет"})
    assert error.value.code == code and len(fake.calls) == len(script)
    assert error.value.status == (502 if code == "E_MODEL_UNAVAILABLE" else 422)


def test_heal_unavailable_model_is_retried_not_cached(
    client: TestClient, config: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed_heal(client, config, 2)
    down = [True]

    def respond(task: str, data: Data) -> Data | Reply:
        assert task == "heal_pair", task
        if down[0]:
            return DOWN
        return {
            "relation": "duplicate",
            "confidence": 0.95,
            "explanation": "Правила об одном и том же.",
            "evidence": evidence(data),
            "suggested_fix": [],
        }

    ag = agent(client, tmp_path, monkeypatch, respond)
    instance = healer(ag)
    retries = ag.settings.limits.retries
    status, report = heal(ag, instance)
    assert report["discarded"] == [{"pair": HEAL_PAIR, "code": "E_MODEL_UNAVAILABLE"}]
    assert status == "paused" and report["retry_needed"]
    assert not pair_checks(ag) and not ag.state.restore("heal", "hashes")
    assert ag.fake.count("heal_pair") == retries
    down[0] = False
    status, report = heal(ag, instance)
    assert status == "done" and not report["retry_needed"] and not report["discarded"]
    assert ag.fake.count("heal_pair") == retries + 1 and len(pair_checks(ag)) == 1
    [finding] = ag.wiki.all("/findings", kind="duplicate")
    assert finding["pages"] == HEAL_PAIR


def test_book_chapter_waits_for_an_unavailable_model(
    client: TestClient, config: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    down = [True]

    def respond(task: str, data: Data) -> Data | Reply:
        if task == "book_chapter":
            n = data["chapter"]["n"]
            return DOWN if n == 2 and down[0] else chapter(candidate(n))
        if task == "classify":
            return NEW
        assert task == "book_review", task
        return EMPTY_REVIEW

    job = book(client, config, tmp_path, monkeypatch, respond)
    with pytest.raises(WikiError) as error:
        job.run()
    assert error.value.code == "E_MODEL_UNAVAILABLE"
    state = job.agent.state
    assert state.restore(job.job, "chapter_done") == 1
    saved = state.rows(
        "SELECT key FROM job_state WHERE job_id=? AND key LIKE 'chapter:2:%'", (job.job,)
    )
    assert saved == [] and state.restore(job.job, "errors", []) == []
    down[0] = False
    job.run()
    assert set(job.rules()) == set(QUOTES)
    assert state.restore(job.job, "report")["errors"] == []
    retries = job.agent.settings.limits.retries
    chapters = [d["chapter"]["n"] for t, d in job.agent.fake.calls if t == "book_chapter"]
    assert chapters == [1, *[2] * retries, 2, 3]


# An input the model's context cannot hold is refused before any request is sent. The
# model never judged it, so it is neither an answer to repair nor a verdict to keep.

SMALL_CONTEXT = 4096


def test_structured_refuses_input_over_the_context_without_asking_the_model(
    tmp_path: Path,
) -> None:
    settings = agent_config(tmp_path)
    settings.models["chat"].context = SMALL_CONTEXT
    state = AgentState(tmp_path)
    answer = {"intent": "other", "clarification": "Какое правило нужно оформить?"}
    fake = FakeLLM(lambda task, data: answer, check_schema=True)
    model = ModelClient(settings, state, fake.http)
    with pytest.raises(WikiError) as error:
        model.structured("chat", "route", Intent, {"message": "Привет, вики. " * 1000})
    assert error.value.code == "E_MODEL_CONTEXT" and error.value.status == 400
    assert error.value.message == "Контекст модели превышен; уменьшите пакет данных."
    assert fake.calls == [] and model.calls == 0
    assert state.rows("SELECT COUNT(*) n FROM model_calls")[0]["n"] == 0
    # The same client still asks the model about an input that fits.
    assert model.structured("chat", "route", Intent, {"message": "Привет"}) == Intent(**answer)
    assert len(fake.calls) == 1 and model.calls == 1


def test_structured_bad_answer_whose_repair_outgrows_the_context_is_model_output(
    tmp_path: Path,
) -> None:
    """The model did answer; only the repair note after it does not fit. That is its output."""
    settings = agent_config(tmp_path)
    settings.models["chat"].context = SMALL_CONTEXT
    state = AgentState(tmp_path)
    # What completion() admits, in characters of the serialized messages.
    limit = int((SMALL_CONTEXT - SMALL_CONTEXT // 4) * 2.5)
    # The prompt around the message, measured on the request a model actually receives.
    answer = {"intent": "other", "clarification": None}
    probe = FakeLLM(lambda task, data: answer, check_schema=True)
    ModelClient(settings, state, probe.http).structured("chat", "route", Intent, {"message": ""})
    base = len(json.dumps(probe.requests[0]["messages"], ensure_ascii=False))
    # The input fits with 20 characters to spare; the note on a bad answer is far longer.
    message = "а" * (limit - base - 20)
    # Truncated JSON is what a model cut off by max_tokens actually sends.
    fake = FakeLLM(lambda task, data: Reply(content='{"intent": "intake"'), check_schema=True)
    model = ModelClient(settings, state, fake.http)
    with pytest.raises(WikiError) as error:
        model.structured("chat", "route", Intent, {"message": message})
    assert error.value.code == "E_MODEL_OUTPUT" and error.value.status == 422
    assert error.value.details == [{"error": "Контекст модели превышен; уменьшите пакет данных."}]
    assert fake.calls == [("route", {"message": message})] and model.calls == 1


def test_structured_retry_after_an_outage_resends_the_same_messages(tmp_path: Path) -> None:
    """A 503 carries no answer to correct, so no repair note joins the retried request."""
    answer = {"intent": "other", "clarification": "Какое правило нужно оформить?"}
    replies: list[Data | Reply] = [DOWN, answer]
    fake = FakeLLM(lambda task, data: replies.pop(0), check_schema=True)
    model = ModelClient(agent_config(tmp_path), AgentState(tmp_path), fake.http)
    assert model.structured("chat", "route", Intent, {"message": "Привет"}) == Intent(**answer)
    assert replies == [] and model.calls == 2
    first, second = fake.requests
    assert len(first["messages"]) == 2 and second["messages"] == first["messages"]


def grow_rule(client: TestClient, config: Settings, page_id: str, chars: int) -> None:
    """A person writes a rule far longer than the planner's context holds."""
    fs = SafeFS(config.wiki_root)
    path = "wiki/rules/" + page_id.removeprefix("rule-") + ".md"
    line = "Записывай в журнал идентификатор запроса и итог операции.\n"
    fs.write(path, fs.read(path) + "\n" + line * (chars // len(line)))
    GitRepo(config.wiki_root).commit("A very long rule", "alice")
    client.app.state.runtime.reindex()


def test_heal_pair_over_the_context_is_reported_not_cached(
    client: TestClient, config: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed_heal(client, config, 4)
    grow_rule(client, config, "rule-heal-03", 40000)

    def respond(task: str, data: Data) -> Data:
        assert task == "heal_pair", task
        assert "rule-heal-03" not in {p["id"] for p in data["pages"]}
        return {
            "relation": "none",
            "confidence": 0.99,
            "explanation": "Нет проблемы.",
            "evidence": [],
            "suggested_fix": [],
        }

    ag = agent(client, tmp_path, monkeypatch, respond)
    ag.settings.models["planner"].context = SMALL_CONTEXT
    instance = healer(ag)

    def sweep() -> tuple[str, Data]:
        job = ag.state.job("heal", ag.wiki.check_writer(), {"scope": "full"})
        instance.run(job, {"scope": "full"})
        status = ag.state.rows("SELECT status FROM jobs WHERE id=?", (job,))[0]["status"]
        return str(status), dict(ag.state.restore(job, "report"))

    refused = [{"pair": ["rule-heal-02", "rule-heal-03"], "code": "E_MODEL_CONTEXT"}]
    status, report = sweep()
    # Not a pause: the same pages would be refused again, so there is nothing to wait for.
    assert status == "done" and not report["retry_needed"] and not report["budget_exhausted"]
    assert report["discarded"] == refused
    assert report["checked_pairs"] == 1 and report["model_calls"] == 1
    # The pair beside it is judged by the model; the refused one is not kept as checked.
    assert ag.fake.count("heal_pair") == 1
    assert [(c["a_id"], c["b_id"]) for c in pair_checks(ag)] == [("rule-heal-00", "rule-heal-01")]
    assert sorted(ag.state.restore("heal", "hashes")) == [f"rule-heal-{n:02}" for n in range(4)]
    status, report = sweep()
    # The next sweep tries the pair again and says so again; the checked pair stays cached.
    assert status == "done" and not report["retry_needed"]
    assert report["discarded"] == refused
    assert report["checked_pairs"] == 0 and report["model_calls"] == 0
    assert ag.fake.count("heal_pair") == 1 and len(pair_checks(ag)) == 1


def long_chapter_book() -> bytes:
    """The handbook with chapter 2 grown past what the planner's context holds."""
    source = Path(__file__).parent / "fixtures/books/handbook.epub"
    stream = io.BytesIO()
    with (
        zipfile.ZipFile(source) as original,
        zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive,
    ):
        for item in original.infolist():
            data = original.read(item.filename)
            if item.filename == "chapter2.html":
                detail = "<p>Original chapter 2 explanation goes on in more detail.</p>" * 280
                data = data.replace(b"</body>", detail.encode() + b"</body>")
            archive.writestr(item, data)
    return stream.getvalue()


def test_book_chapter_over_the_context_is_reported_and_skipped(
    client: TestClient, config: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def respond(task: str, data: Data) -> Data:
        if task == "book_chapter":
            return chapter(candidate(data["chapter"]["n"]))
        if task == "classify":
            return NEW
        assert task == "book_review", task
        return EMPTY_REVIEW

    job = book(client, config, tmp_path, monkeypatch, respond, data=long_chapter_book())
    # Room for chapters 1 and 3 and their classification, not for the grown chapter 2.
    job.agent.settings.models["planner"].context = 2 * SMALL_CONTEXT
    job.run()
    report = job.agent.state.restore(job.job, "report")
    chapters = [d["chapter"]["n"] for t, d in job.agent.fake.calls if t == "book_chapter"]
    # Chapter 2 never reached the model: it is reported by its own code, not as a bad answer.
    assert report["errors"] == [{"chapter": 2, "code": "E_MODEL_CONTEXT"}]
    assert chapters == [1, 3]
    assert set(job.rules()) == {QUOTES[0], QUOTES[2]} and report["candidates"] == 2
    assert report["chapters_done"] == report["chapters_total"] == 3
    assert job.agent.wiki.request("GET", "/proposals/" + job.pid())["status"] == "submitted"
