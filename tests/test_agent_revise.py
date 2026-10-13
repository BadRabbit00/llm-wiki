"""Chat edits of existing pages (issue #9): real wikisvc and git, only the model is scripted."""

import json
import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import httpx
import pytest
from agent_helpers import agent_config, event, seed_chat, tokens, wiki_client
from fake_llm import FakeLLM, claim
from fastapi.testclient import TestClient

from wikiagent.api import create_app
from wikiagent.client import WikiClient
from wikiagent.models import ModelClient
from wikiagent.state import AgentState
from wikisvc.config import Settings
from wikisvc.services.auth import Auth

DISCLAIMER = "Примеры предложены моделью, проверьте."
NO_EXAMPLES = "Примеров нет: модель их не предложила. Добавьте до принятия."
INTAKE = "Пиши только асинхронный код Python"
ADD_EXAMPLES = "Добавь примеры, их почему-то нету"
REWRITE = "Перепиши обоснование"
EXAMPLES = "Так:\n\nawait client.get(url)\n\nНе так:\n\nrequests.get(url)"
RATIONALE = "Синхронный вызов в обработчике останавливает цикл событий для всех запросов."
NEW = [{"relation": "new", "confidence": 1, "reason": "Нет совпадений."}]
PATCH_COUNT = (
    "Количество совпадений replace_text отличается от expect_count. "
    "Прочитайте актуальный текст и уточните old/expect_count."
)


def refusal(reason: str) -> dict[str, Any]:
    return {
        "code": "E_AGENT_REVISE_TARGET",
        "message": "Это предложение нельзя изменить через агента.",
        "hint": "Откройте черновик из своего чата или попросите ревьюера.",
        "details": [{"reason": reason}],
    }


def locate(page: str = "rule-async-only", *headings: str) -> dict[str, Any]:
    return {"targets": [{"page": page, "headings": list(headings or ["Примеры"])}]}


def revise(page: str = "rule-async-only", summary: str = "", **edit: Any) -> dict[str, Any]:
    return {
        "pages": [
            {
                "page": page,
                "edits": [
                    edit or {"op": "replace_section", "heading": "Примеры", "text": EXAMPLES}
                ],
                "summary": summary or "раздел „Примеры“: добавлены примеры",
            }
        ]
    }


class Script:
    """Model answers per task. The last answer repeats, as a stubborn model would."""

    def __init__(
        self,
        answers: dict[str, list[dict[str, Any]]] | None = None,
        claims: list[dict[str, Any]] | None = None,
        relations: list[dict[str, Any]] | None = None,
    ) -> None:
        self.answers = answers or {}
        self.claims = claims or [claim(good_example="", bad_example="")]
        self.relations = relations or NEW
        # Real changes by people that land while the model is still generating a task.
        self.meanwhile: dict[str, list[Callable[[], None]]] = {}

    def __call__(self, task: str, data: dict[str, Any]) -> dict[str, Any]:
        if task == "route":
            return {"intent": "intake" if data["message"] == INTAKE else "revise"}
        if task == "extract_claims":
            return {"claims": self.claims}
        if task == "classify":
            return {"relations": self.relations}
        if self.meanwhile.get(task):
            self.meanwhile[task].pop(0)()
        queue = self.answers[task]
        return queue.pop(0) if len(queue) > 1 else queue[0]


class Stack:
    def __init__(self, client: TestClient, chat: TestClient, fake: FakeLLM, wiki: WikiClient):
        self.client, self.chat, self.fake, self.wiki = client, chat, fake, wiki
        self.auth = Auth(client.app.state.runtime.state)

    def person(self, name: str, role: str = "writer") -> str:
        return self.auth.create(name, role, "restricted", person=name, kind="human")

    def login(self, token: str) -> None:
        self.chat.headers["Authorization"] = "Bearer " + token

    def session(self, bind: dict[str, str] | None = None) -> str:
        response = self.chat.post("/chat/sessions", json={"bind": bind} if bind else {})
        assert response.status_code == 200, response.text
        return str(response.json()["id"])

    def send(self, sid: str, text: str) -> httpx.Response:
        return self.chat.post(f"/chat/sessions/{sid}/messages", json={"text": text})

    def draft(self) -> tuple[str, str]:
        sid = self.session()
        return sid, str(event(self.send(sid, INTAKE))["plan"]["proposal"])

    def proposal(self, pid: str) -> dict[str, Any]:
        response = self.client.get("/api/v1/proposals/" + pid)
        assert response.status_code == 200, response.text
        result: dict[str, Any] = response.json()
        return result

    def bodies(self, pid: str) -> dict[str, str]:
        return {page["id"]: page["body_md"] for page in self.proposal(pid)["pages"]}

    def tasks(self) -> list[str]:
        return [task for task, _ in self.fake.calls]

    def data(self, task: str) -> list[dict[str, Any]]:
        return [data for name, data in self.fake.calls if name == task]


@contextmanager
def stack(
    client: TestClient,
    config: Settings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    script: Script,
) -> Iterator[Stack]:
    seed_chat(client, config)
    agent, human = tokens(client)
    monkeypatch.setenv("WIKIAGENT_TOKEN", agent)
    client.headers["Authorization"] = "Bearer " + human
    settings = agent_config(tmp_path / "agent")
    wiki = wiki_client(client, settings)
    fake = FakeLLM(script)
    models = ModelClient(settings, AgentState(settings.state_dir), fake.http)
    with TestClient(create_app(settings, wiki, models)) as chat:
        chat.headers["Authorization"] = "Bearer " + human
        yield Stack(client, chat, fake, wiki)
    assert wiki.forbidden_attempts == 0


def failure(response: httpx.Response) -> dict[str, Any]:
    for block in response.text.split("\n\n"):
        if block.startswith("event: error\n"):
            error: dict[str, Any] = json.loads(block.split("data: ", 1)[1])["error"]
            return error
    raise AssertionError(response.text)


def replaced(body: str, heading: str, content: str) -> str:
    """The body with exactly one section's content swapped, everything else byte-equal."""
    start = body.index(f"## {heading}\n") + len(f"## {heading}\n")
    end = body.find("\n## ", start)
    tail = body[end + 1 :] if end != -1 else ""
    return body[:start] + "\n" + content + "\n" + ("\n" + tail if tail else "")


def test_bound_draft_examples_are_added_without_touching_other_sections(
    client: TestClient, config: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    script = Script({"locate_revision": [locate()], "revise_page": [revise()]})
    with stack(client, config, tmp_path, monkeypatch, script) as s:
        s.login(s.person("dave"))
        draft_sid, pid = s.draft()
        before = s.bodies(pid)
        rule = before["rule-async-only"]
        assert rule.endswith("## Примеры\n\n" + NO_EXAMPLES + "\n"), rule
        sid = s.session({"type": "proposal", "id": pid})
        result = event(s.send(sid, ADD_EXAMPLES))

        assert result["text"] == "Изменено: rule-async-only — раздел „Примеры“: добавлены примеры"
        plan = result["plan"]
        assert plan["items"] == [
            {
                "n": 1,
                "action": "revise_page",
                "target": "rule-async-only",
                "headings": ["Примеры"],
                "reason": "раздел „Примеры“: добавлены примеры",
            }
        ]
        assert plan["proposal"] == pid and plan["questions"] == []
        assert plan["assumptions"] == [DISCLAIMER] and plan["owner"] == "dave"
        assert plan["validation"]["errors"] == []
        assert [p["id"] for p in plan["preview_diff"]["pages"]] == sorted(before)
        after = s.bodies(pid)
        # The model left the disclaimer out; the agent puts it first, in code.
        assert after == {
            **before,
            "rule-async-only": replaced(rule, "Примеры", DISCLAIMER + "\n\n" + EXAMPLES),
        }
        proposal = s.proposal(pid)
        assert proposal["status"] == "draft" and proposal["notes"] == plan
        # The request never reached claim extraction, which turned it into not_rule.
        assert s.tasks().count("extract_claims") == 1
        source = "src-chat-" + pid[:12]
        assert sorted(s.data("locate_revision")[0]["pages"], key=lambda p: p["id"]) == [
            {
                "id": "rule-async-only",
                "type": "rule",
                "title": "Асинхронный Python",
                "summary": "Используй только асинхронный код в обработчиках Python.",
                "headings": ["Правило", "Обоснование", "Примеры"],
            },
            {
                "id": source,
                "type": "source",
                "title": "Решения чата " + draft_sid[:12],
                "summary": "Решения команды из переписки, сохранённые для проверки правил.",
                "headings": ["Кратко", "Ключевые факты", "Что изменилось в вики"],
            },
        ]
        assert s.data("revise_page") == [
            {
                "message": ADD_EXAMPLES,
                "sections": [
                    {"page": "rule-async-only", "heading": "Примеры", "text": NO_EXAMPLES}
                ],
            }
        ]
        stored = s.chat.get("/chat/sessions/" + sid).json()
        assert stored["plan"] == plan and stored["messages"][-1]["text"] == result["text"]


def test_session_draft_is_revised_and_disclaimer_is_not_doubled(
    client: TestClient, config: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    text = DISCLAIMER + "\n\n" + EXAMPLES
    script = Script(
        {
            "locate_revision": [locate()],
            "revise_page": [revise(op="replace_section", heading="Примеры", text=text)],
        }
    )
    with stack(client, config, tmp_path, monkeypatch, script) as s:
        sid, pid = s.draft()
        before = s.bodies(pid)
        plan = event(s.send(sid, ADD_EXAMPLES))["plan"]
        assert plan["proposal"] == pid and plan["owner"] == "alice"
        after = s.bodies(pid)
        assert after == {
            **before,
            "rule-async-only": replaced(before["rule-async-only"], "Примеры", text),
        }
        assert after["rule-async-only"].count(DISCLAIMER) == 1


def test_section_can_be_added_after_a_chosen_one(
    client: TestClient, config: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    script = Script(
        {
            "locate_revision": [locate("rule-async-only", "Обоснование")],
            "revise_page": [
                revise(
                    summary="добавлен раздел „Исключения“",
                    op="add_section",
                    heading="Исключения",
                    after="Обоснование",
                    text="Скрипты миграций выполняются вне обработчиков.",
                )
            ],
        }
    )
    with stack(client, config, tmp_path, monkeypatch, script) as s:
        sid, pid = s.draft()
        rule = s.bodies(pid)["rule-async-only"]
        plan = event(s.send(sid, "Добавь раздел про исключения"))["plan"]
        assert plan["items"][0]["headings"] == ["Исключения"]
        assert plan["assumptions"] == []
        cut = rule.index("## Примеры")
        assert s.bodies(pid)["rule-async-only"] == (
            rule[:cut]
            + "## Исключения\n\nСкрипты миграций выполняются вне обработчиков.\n\n"
            + rule[cut:]
        )


@pytest.mark.parametrize(
    ("located", "revised"),
    [
        (locate("rule-http-requests-sync"), None),
        (locate("rule-async-only", "Источники"), None),
        (locate(), revise("rule-http-requests-sync")),
        (locate(), revise(op="replace_section", heading="Правило", text="Пиши как хочешь.")),
        (
            locate(),
            revise(
                op="replace_text",
                old="Используй только асинхронный код",
                text="Используй любой код",
            ),
        ),
        (
            locate(),
            revise(op="add_section", heading="Ещё", after="Правило", text="Новый раздел."),
        ),
    ],
    ids=[
        "foreign-page",
        "unknown-heading",
        "revise-unlocated-page",
        "revise-unlocated-section",
        "text-outside-sections",
        "insert-after-unlocated",
    ],
)
def test_model_reaching_outside_what_it_was_shown_is_refused(
    client: TestClient,
    config: Settings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    located: dict[str, Any],
    revised: dict[str, Any] | None,
) -> None:
    answers = {"locate_revision": [located], **({"revise_page": [revised]} if revised else {})}
    with stack(client, config, tmp_path, monkeypatch, Script(answers)) as s:
        _, pid = s.draft()
        before = s.proposal(pid)
        sid = s.session({"type": "proposal", "id": pid})
        assert failure(s.send(sid, ADD_EXAMPLES)) == refusal("scope")
        assert s.tasks().count("revise_page") == (1 if revised else 0)
        after = s.proposal(pid)
        assert after["pages"] == before["pages"] and after["notes"] == before["notes"]


@pytest.mark.parametrize("close", ["accept", "abandon"])
def test_closed_proposal_is_refused(
    client: TestClient,
    config: Settings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    close: str,
) -> None:
    script = Script({"locate_revision": [locate()], "revise_page": [revise()]})
    with stack(client, config, tmp_path, monkeypatch, script) as s:
        _, pid = s.draft()
        if close == "accept":
            notes = s.proposal(pid)["notes"]
            response = s.client.post(f"/api/v1/proposals/{pid}/accept", json=notes["accept_body"])
            assert response.status_code == 200, response.text
        else:
            s.wiki.request("POST", f"/proposals/{pid}/abandon")
        before = s.proposal(pid)
        sid = s.session({"type": "proposal", "id": pid})
        assert failure(s.send(sid, ADD_EXAMPLES)) == refusal("state")
        assert "locate_revision" not in s.tasks()
        assert s.proposal(pid)["pages"] == before["pages"]


def test_proposal_written_by_a_person_is_refused(
    client: TestClient, config: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from test_review_policy import candidate

    with stack(client, config, tmp_path, monkeypatch, Script()) as s:
        dave = s.person("dave")
        client.headers["Authorization"] = "Bearer " + dave
        pid = candidate(client)
        before = s.proposal(pid)
        assert before["author"] == "dave"
        s.login(dave)
        sid = s.session({"type": "proposal", "id": pid})
        assert failure(s.send(sid, ADD_EXAMPLES)) == refusal("author")
        assert s.tasks() == ["route"]
        assert s.proposal(pid)["pages"] == before["pages"]


def namesake(s: Stack) -> str:
    """A person whose display name is the agent token's name; their identity is their own."""
    token = s.auth.create(
        "mallory-sso",
        "writer",
        "restricted",
        person="mallory",
        kind="human",
        display_name="chat-agent",
    )
    actor = s.wiki.whoami(token)
    assert (actor["name"], actor["person"]) == ("chat-agent", "mallory")
    return token


def test_draft_of_the_agents_namesake_is_refused(
    client: TestClient, config: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from test_review_policy import candidate

    content = "Так:\n\nlogger.info('event')\n\nНе так:\n\nprint('event')"
    script = Script(
        {
            "locate_revision": [locate("rule-logging")],
            "revise_page": [
                revise("rule-logging", op="replace_section", heading="Примеры", text=content)
            ],
        }
    )
    with stack(client, config, tmp_path, monkeypatch, script) as s:
        client.headers["Authorization"] = "Bearer " + namesake(s)
        pid = candidate(client)
        before = s.proposal(pid)
        assert (before["author"], before["author_identity"]) == ("chat-agent", "mallory")
        # alice is a reviewer, so only the author check stands between her and this draft.
        sid = s.session({"type": "proposal", "id": pid})
        assert failure(s.send(sid, ADD_EXAMPLES)) == refusal("author")
        assert s.tasks() == ["route"]
        assert s.proposal(pid) == before


def test_bound_rule_does_not_continue_a_namesakes_draft(
    client: TestClient, config: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from test_proposals import proposal

    from wikiagent.planner.revise import Reviser

    target = "rule-http-requests-sync"
    script = Script(
        {
            "locate_revision": [locate(target, "Обоснование")],
            "revise_page": [
                revise(
                    target,
                    summary="раздел „Обоснование“ переписан",
                    op="replace_section",
                    heading="Обоснование",
                    text=RATIONALE,
                )
            ],
        }
    )
    with stack(client, config, tmp_path, monkeypatch, script) as s:
        published = s.wiki.request("GET", "/pages/" + target)
        client.headers["Authorization"] = "Bearer " + namesake(s)
        foreign = proposal(client, "Своя правка")
        response = client.patch(
            f"/api/v1/proposals/{foreign}/pages/{target}",
            json={
                "base_version": published["version"],
                "ops": [{"op": "append_to_section", "heading": "Примеры", "text": "Своё."}],
            },
        )
        assert response.status_code == 200, response.text
        before = s.proposal(foreign)
        token = s.person("ivan")
        # The draft a session's plan points at must be the agent's own to be continued; a plan
        # cannot name another's draft through chat, so the reviser is handed one directly.
        session = {
            "id": "x" * 32,
            "owner": "ivan",
            "bind": {"type": "rule", "id": target},
            "plan": {"proposal": foreign},
        }
        plan = Reviser(s.wiki, s.chat.app.state.models).run(REWRITE, session, s.wiki.whoami(token))[
            "plan"
        ]
        assert plan["proposal"] != foreign and plan["owner"] == "ivan"
        mine = s.proposal(plan["proposal"])
        assert (mine["author"], mine["author_identity"]) == ("chat-agent", "chat-agent")
        [page] = mine["pages"]
        assert page["body_md"] == replaced(published["body_md"], "Обоснование", RATIONALE)
        assert s.proposal(foreign) == before


def test_only_the_draft_owner_or_a_reviewer_may_revise(
    client: TestClient, config: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    script = Script({"locate_revision": [locate()], "revise_page": [revise()]})
    with stack(client, config, tmp_path, monkeypatch, script) as s:
        s.login(s.person("dave"))
        _, pid = s.draft()
        before = s.bodies(pid)
        s.login(s.person("bob"))
        sid = s.session({"type": "proposal", "id": pid})
        assert failure(s.send(sid, ADD_EXAMPLES)) == refusal("owner")
        assert s.bodies(pid) == before and "locate_revision" not in s.tasks()
        s.login(s.person("carol", "reviewer"))
        sid = s.session({"type": "proposal", "id": pid})
        plan = event(s.send(sid, ADD_EXAMPLES))["plan"]
        assert plan["proposal"] == pid
        # The reviewer edits the draft, but it still belongs to the session that made it.
        assert plan["owner"] == "dave" and s.proposal(pid)["notes"]["owner"] == "dave"
        assert s.bodies(pid) == {
            **before,
            "rule-async-only": replaced(
                before["rule-async-only"], "Примеры", DISCLAIMER + "\n\n" + EXAMPLES
            ),
        }


def test_agent_draft_without_recorded_owner_is_open_only_to_reviewers(
    client: TestClient, config: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from test_review_policy import candidate

    content = "Так:\n\nlogger.info('event')\n\nНе так:\n\nprint('event')"
    script = Script(
        {
            "locate_revision": [locate("rule-logging")],
            "revise_page": [
                revise("rule-logging", op="replace_section", heading="Примеры", text=content)
            ],
        }
    )
    with stack(client, config, tmp_path, monkeypatch, script) as s:
        # A draft the agent token wrote without chat notes, as before notes.owner existed.
        client.headers["Authorization"] = "Bearer " + os.environ["WIKIAGENT_TOKEN"]
        pid = candidate(client)
        client.headers["Authorization"] = "Bearer " + s.person("erin", "reviewer")
        before = s.proposal(pid)
        assert before["notes"] is None and before["author"] == "chat-agent"
        s.login(s.person("dave"))
        sid = s.session({"type": "proposal", "id": pid})
        assert failure(s.send(sid, ADD_EXAMPLES)) == refusal("owner")
        s.login(s.person("carol", "reviewer"))
        sid = s.session({"type": "proposal", "id": pid})
        plan = event(s.send(sid, ADD_EXAMPLES))["plan"]
        assert "owner" not in plan
        body = before["pages"][0]["body_md"]
        assert s.bodies(pid) == {
            "rule-logging": replaced(body, "Примеры", DISCLAIMER + "\n\n" + content)
        }


def test_ambiguous_replace_text_is_retried_then_reported(
    client: TestClient, config: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ambiguous = revise(
        summary="раздел „Примеры“: добавлен таймаут",
        op="replace_text",
        old="client.get(url)",
        text="client.get(url, timeout=10)",
    )
    script = Script(
        {"locate_revision": [locate()], "revise_page": [ambiguous]},
        claims=[claim(bad_example="client.get(url) без await")],
    )
    with stack(client, config, tmp_path, monkeypatch, script) as s:
        sid, pid = s.draft()
        before = s.proposal(pid)
        error = failure(s.send(sid, "Добавь таймаут в примеры"))
        assert error["code"] == "E_PATCH_COUNT"
        assert error["message"] + " " + error["hint"] == PATCH_COUNT
        calls = s.data("revise_page")
        assert len(calls) == 3 and "error" not in calls[0]
        assert [c["error"] for c in calls[1:]] == [PATCH_COUNT, PATCH_COUNT]
        assert [c["previous"] for c in calls[1:]] == [ambiguous, ambiguous]
        after = s.proposal(pid)
        assert after["pages"] == before["pages"] and after["notes"] == before["notes"]


def test_service_error_reaches_the_model_and_the_retry_applies(
    client: TestClient, config: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ambiguous = revise(
        summary="раздел „Примеры“: добавлен таймаут",
        op="replace_text",
        old="client.get(url)",
        text="client.get(url, timeout=10)",
    )
    fixed = json.loads(json.dumps(ambiguous))
    fixed["pages"][0]["edits"][0]["expect_count"] = 2
    script = Script(
        {"locate_revision": [locate()], "revise_page": [ambiguous, fixed]},
        claims=[claim(bad_example="client.get(url) без await")],
    )
    with stack(client, config, tmp_path, monkeypatch, script) as s:
        sid, pid = s.draft()
        before = s.bodies(pid)
        rule = before["rule-async-only"]
        plan = event(s.send(sid, "Добавь таймаут в примеры"))["plan"]
        assert plan["items"][0]["headings"] == ["Примеры"]
        assert s.data("revise_page")[1]["error"] == PATCH_COUNT
        examples = rule[rule.index("## Примеры\n\n") + len("## Примеры\n\n") :].rstrip("\n")
        assert s.bodies(pid) == {
            **before,
            "rule-async-only": replaced(
                rule, "Примеры", examples.replace("client.get(url)", "client.get(url, timeout=10)")
            ),
        }


def test_accept_plan_and_open_questions_survive_a_revision(
    client: TestClient, config: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    script = Script(
        {
            "locate_revision": [locate("rule-async-only", "Обоснование")],
            "revise_page": [
                revise(
                    summary="раздел „Обоснование“ переписан",
                    op="replace_section",
                    heading="Обоснование",
                    text=RATIONALE,
                )
            ],
        },
        claims=[claim(level_guess="must")],
        relations=[
            {
                "relation": "conflicts_with",
                "target": "rule-http-requests-sync",
                "confidence": 0.95,
                "quote": "Используй requests для синхронных HTTP запросов Python.",
                "reason": "requests блокирует асинхронный обработчик.",
            }
        ],
    )
    with stack(client, config, tmp_path, monkeypatch, script) as s:
        sid, pid = s.draft()
        notes = s.proposal(pid)["notes"]
        assert notes["accept_body"]["promote"] == [
            {"id": "rule-async-only", "level": "must", "priority": 3, "applies_to": ["lang:python"]}
        ]
        assert notes["needs_double_confirm"] is True
        assert [q["id"] for q in notes["questions"]] == ["conflict-rule-http-requests-sync"]
        rule = s.bodies(pid)["rule-async-only"]
        plan = event(s.send(sid, REWRITE))["plan"]
        assert plan["accept_body"] == notes["accept_body"]
        assert plan["needs_double_confirm"] is True
        assert plan["questions"] == notes["questions"]
        assert plan["assumptions"] == []
        stored = s.proposal(pid)["notes"]
        assert stored["accept_body"] == notes["accept_body"] and stored["owner"] == "alice"
        assert s.bodies(pid)["rule-async-only"] == replaced(rule, "Обоснование", RATIONALE)


def test_bound_rule_is_revised_in_a_new_proposal(
    client: TestClient, config: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = "rule-http-requests-sync"
    script = Script(
        {
            "locate_revision": [locate(target, "Обоснование")],
            "revise_page": [
                revise(
                    target,
                    summary="раздел „Обоснование“ переписан",
                    op="replace_section",
                    heading="Обоснование",
                    text=RATIONALE,
                )
            ],
        }
    )
    with stack(client, config, tmp_path, monkeypatch, script) as s:
        published = s.wiki.request("GET", "/pages/" + target)
        sid = s.session({"type": "rule", "id": target})
        result = event(s.send(sid, REWRITE))
        plan = result["plan"]
        assert result["text"] == f"Изменено: {target} — раздел „Обоснование“ переписан"
        assert plan["accept_body"] == {"promote": [], "deprecate": []}
        assert plan["needs_double_confirm"] is False and plan["owner"] == "alice"
        assert plan["validation"]["errors"] == []
        proposal = s.proposal(plan["proposal"])
        assert (proposal["title"], proposal["author"], proposal["kind"], proposal["status"]) == (
            f"Правка {target} из чата",
            "chat-agent",
            "chat",
            "draft",
        )
        assert proposal["notes"] == plan
        [page] = proposal["pages"]
        assert page["body_md"] == replaced(published["body_md"], "Обоснование", RATIONALE)
        assert (page["lifecycle"], page["level"], page["owner"]) == (
            "active",
            "should",
            "team-python",
        )
        assert s.wiki.request("GET", "/pages/" + target) == published
        accepted = s.client.post(
            f"/api/v1/proposals/{plan['proposal']}/accept", json=plan["accept_body"]
        )
        assert accepted.status_code == 200, accepted.text
        assert s.wiki.request("GET", "/pages/" + target)["body_md"] == page["body_md"]


def test_published_text_outside_the_chosen_section_is_not_replaced(
    client: TestClient, config: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = "rule-http-requests-sync"
    # Every seeded section repeats this sentence; only «Обоснование» was shown to the model.
    script = Script(
        {
            "locate_revision": [locate(target, "Обоснование")],
            "revise_page": [
                revise(
                    target,
                    op="replace_text",
                    old="Выгрузка счёта.",
                    expect_count=3,
                    text="Синхронный HTTP.",
                )
            ],
        }
    )
    with stack(client, config, tmp_path, monkeypatch, script) as s:
        sid = s.session({"type": "rule", "id": target})
        assert failure(s.send(sid, REWRITE)) == refusal("scope")
        assert (
            s.client.get("/api/v1/proposals", params={"author": "chat-agent"}).json()["items"] == []
        )


@pytest.mark.parametrize(
    "bad",
    [
        {"op": "replace_section", "heading": "Примеры", "text": "## Примеры\n\n" + EXAMPLES},
        {
            "op": "replace_section",
            "heading": "Примеры",
            "text": "Так:\n\nawait client.get(url)\n\n## Обоснование\n\nДругое.",
        },
        {"op": "replace_section", "text": EXAMPLES},
        {"op": "replace_text", "text": EXAMPLES},
    ],
    ids=["leading-heading", "inner-heading", "no-heading-field", "no-old-field"],
)
def test_malformed_edit_goes_back_to_the_model(
    client: TestClient,
    config: Settings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    bad: dict[str, Any],
) -> None:
    script = Script({"locate_revision": [locate()], "revise_page": [revise(**bad), revise()]})
    with stack(client, config, tmp_path, monkeypatch, script) as s:
        sid, pid = s.draft()
        before = s.bodies(pid)
        event(s.send(sid, ADD_EXAMPLES))
        # Rejected by the schema inside one structured call: the same data is asked again,
        # no service error was involved.
        assert s.data("revise_page") == [s.data("revise_page")[0]] * 2
        assert "error" not in s.data("revise_page")[0]
        after = s.bodies(pid)["rule-async-only"]
        assert after == replaced(
            before["rule-async-only"], "Примеры", DISCLAIMER + "\n\n" + EXAMPLES
        )
        assert after.count("## Примеры") == 1 and after.count("## Обоснование") == 1


def test_revision_without_a_target_is_refused(
    client: TestClient, config: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with stack(client, config, tmp_path, monkeypatch, Script()) as s:
        sid = s.session()
        assert failure(s.send(sid, ADD_EXAMPLES)) == refusal("no_target")
        assert s.tasks() == ["route"]


@pytest.mark.parametrize(
    "answers",
    [
        {"locate_revision": [{"targets": []}]},
        {"locate_revision": [locate()], "revise_page": [{"pages": []}]},
    ],
    ids=["nothing-located", "nothing-revised"],
)
def test_request_that_is_not_an_edit_gets_a_question(
    client: TestClient,
    config: Settings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    answers: dict[str, list[dict[str, Any]]],
) -> None:
    with stack(client, config, tmp_path, monkeypatch, Script(answers)) as s:
        sid, pid = s.draft()
        before = s.proposal(pid)
        result = event(s.send(sid, "Сделай получше"))
        assert result == {"text": "Уточните, что и в каком разделе изменить."}
        after = s.proposal(pid)
        assert after["pages"] == before["pages"] and after["notes"] == before["notes"]
        assert s.chat.get("/chat/sessions/" + sid).json()["plan"] == before["notes"]


def test_any_page_of_the_draft_can_be_revised(
    client: TestClient, config: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    facts = "Команда отказалась от синхронных обработчиков после инцидента с таймаутами."
    script = Script()
    with stack(client, config, tmp_path, monkeypatch, script) as s:
        sid, pid = s.draft()
        # The source page ID depends on the proposal, so the model learns it only now.
        source = "src-chat-" + pid[:12]
        script.answers = {
            "locate_revision": [locate(source, "Ключевые факты")],
            "revise_page": [
                revise(
                    source,
                    summary="раздел „Ключевые факты“ уточнён",
                    op="replace_section",
                    heading="Ключевые факты",
                    text=facts,
                )
            ],
        }
        before = s.bodies(pid)
        plan = event(s.send(sid, "Уточни ключевые факты в источнике"))["plan"]
        assert plan["items"][0]["target"] == source and plan["assumptions"] == []
        assert s.bodies(pid) == {
            **before,
            source: replaced(before[source], "Ключевые факты", facts),
        }


def test_reviser_never_edits_pages_above_the_callers_clearance(
    client: TestClient, config: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The HTTP layer already refuses such callers; the reviser does not rely on it."""
    from test_proposals import payload, proposal

    from wikiagent.planner.revise import Reviser
    from wikisvc.domain.errors import WikiError

    with stack(client, config, tmp_path, monkeypatch, Script()) as s:
        client.headers["Authorization"] = "Bearer " + os.environ["WIKIAGENT_TOKEN"]
        pid = proposal(client)
        page = payload()
        page["frontmatter"]["sensitivity"] = "restricted"
        response = client.put(f"/api/v1/proposals/{pid}/pages/term-new", json=page)
        assert response.status_code == 200, response.text
        token = s.auth.create("ivan", "reviewer", "internal", person="ivan", kind="human")
        actor = s.wiki.whoami(token)
        session = {"id": "x" * 32, "owner": "ivan", "bind": {"type": "proposal", "id": pid}}
        reviser = Reviser(s.wiki, s.chat.app.state.models)
        with pytest.raises(WikiError) as error:
            reviser.run(ADD_EXAMPLES, {**session, "plan": None}, actor)
        assert error.value.code == "E_NOT_FOUND" and s.tasks() == []


def test_second_edit_of_a_bound_rule_continues_its_draft(
    client: TestClient, config: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = "rule-http-requests-sync"
    script = Script(
        {
            "locate_revision": [locate(target, "Обоснование"), locate(target, "Примеры")],
            "revise_page": [
                revise(
                    target,
                    summary="раздел „Обоснование“ переписан",
                    op="replace_section",
                    heading="Обоснование",
                    text=RATIONALE,
                ),
                revise(target, op="replace_section", heading="Примеры", text=EXAMPLES),
            ],
        }
    )
    with stack(client, config, tmp_path, monkeypatch, script) as s:
        published = s.wiki.request("GET", "/pages/" + target)
        sid = s.session({"type": "rule", "id": target})
        first = event(s.send(sid, REWRITE))["plan"]
        second = event(s.send(sid, ADD_EXAMPLES))["plan"]
        assert second["proposal"] == first["proposal"]
        drafts = s.client.get("/api/v1/proposals", params={"author": "chat-agent"}).json()
        assert [p["pid"] for p in drafts["items"]] == [first["proposal"]]
        [page] = s.proposal(first["proposal"])["pages"]
        assert page["body_md"] == replaced(
            replaced(published["body_md"], "Обоснование", RATIONALE),
            "Примеры",
            DISCLAIMER + "\n\n" + EXAMPLES,
        )
        # The second step saw the draft, with the first edit already in it.
        assert s.data("revise_page")[1]["sections"] == [
            {
                "page": target,
                "heading": "Примеры",
                "text": "Выгрузка счёта. Invoice processing and exports.",
            }
        ]
        assert second["owner"] == "alice" and s.wiki.request("GET", "/pages/" + target) == published


def test_reviewer_reply_keeps_the_draft_owner(
    client: TestClient, config: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    script = Script({"locate_revision": [locate()], "revise_page": [revise()]})
    with stack(client, config, tmp_path, monkeypatch, script) as s:
        s.login(s.person("dave"))
        _, pid = s.draft()
        s.login(s.person("carol", "reviewer"))
        sid = s.session({"type": "proposal", "id": pid})
        assert event(s.send(sid, ADD_EXAMPLES))["plan"]["owner"] == "dave"
        script.claims = [
            claim(
                "rule-http-timeouts",
                text="Всегда задавай таймаут HTTP запросам",
                title="Таймауты HTTP",
                thesis="Задавай явный таймаут каждому HTTP запросу в Python.",
                aliases=["таймаут HTTP", "HTTP timeout"],
            )
        ]
        plan = event(s.send(sid, INTAKE))["plan"]
        assert plan["proposal"] == pid
        proposal = s.proposal(pid)
        assert {p["id"] for p in proposal["pages"]} >= {"rule-async-only", "rule-http-timeouts"}
        assert plan["owner"] == "dave" and proposal["notes"]["owner"] == "dave"


def test_failed_new_revision_draft_is_abandoned(
    client: TestClient, config: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = "rule-http-requests-sync"
    script = Script(
        {
            "locate_revision": [locate(target, "Обоснование")],
            "revise_page": [
                revise(
                    target,
                    summary="раздел „Обоснование“ переписан",
                    op="replace_section",
                    heading="Обоснование",
                    text=RATIONALE,
                )
            ],
        }
    )
    with stack(client, config, tmp_path, monkeypatch, script) as s:
        dave = {"Authorization": "Bearer " + s.person("dave")}
        human = "Человек уточнил обоснование, пока модель писала свою правку."

        def publish() -> None:
            pid = s.client.post("/api/v1/proposals", json={"title": "Уточнение"}, headers=dave)
            pid.raise_for_status()
            number = pid.json()["pid"]
            page = s.client.get("/api/v1/pages/" + target).json()
            for response in (
                s.client.patch(
                    f"/api/v1/proposals/{number}/pages/{target}",
                    headers=dave,
                    json={
                        "base_version": page["version"],
                        "ops": [
                            {"op": "append_to_section", "heading": "Обоснование", "text": human}
                        ],
                    },
                ),
                s.client.post(f"/api/v1/proposals/{number}/submit", headers=dave),
                s.client.post(
                    f"/api/v1/proposals/{number}/accept", json={"promote": [], "deprecate": []}
                ),
            ):
                assert response.status_code == 200, response.text

        script.meanwhile["revise_page"] = [publish]
        sid = s.session({"type": "rule", "id": target})
        error = failure(s.send(sid, REWRITE))
        assert (error["code"], error["message"]) == (
            "E_VERSION_CONFLICT",
            "Версия страницы изменилась.",
        )
        [draft] = s.client.get("/api/v1/proposals", params={"author": "chat-agent"}).json()["items"]
        assert (draft["title"], draft["status"]) == (f"Правка {target} из чата", "abandoned")
        body = s.wiki.request("GET", "/pages/" + target)["body_md"]
        assert human in body and RATIONALE not in body


def test_service_patch_error_is_retried_on_current_text(
    client: TestClient, config: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    old, new = "await client.get(url)", "await client.get(url, timeout=10)"
    first = revise(
        summary="раздел „Примеры“: добавлен таймаут", op="replace_text", old=old, text=new
    )
    fixed = json.loads(json.dumps(first))
    fixed["pages"][0]["edits"][0]["expect_count"] = 2
    script = Script(
        {"locate_revision": [locate()], "revise_page": [first, fixed]},
        claims=[claim(bad_example="")],
    )
    with stack(client, config, tmp_path, monkeypatch, script) as s:
        sid, pid = s.draft()
        carol = {"Authorization": "Bearer " + s.person("carol", "reviewer")}
        extra = "Ещё так:\n\nawait client.get(url) внутри цикла."

        def append() -> None:
            response = s.client.patch(
                f"/api/v1/proposals/{pid}/pages/rule-async-only",
                headers=carol,
                json={"ops": [{"op": "append_to_section", "heading": "Примеры", "text": extra}]},
            )
            assert response.status_code == 200, response.text

        # The dry run sees one occurrence; by PATCH time a reviewer has added a second one.
        script.meanwhile["revise_page"] = [append]
        before = s.bodies(pid)["rule-async-only"]
        event(s.send(sid, "Добавь таймаут в примеры"))
        examples = DISCLAIMER + "\n\nТак:\n\n" + old + "\n\n" + extra
        calls = s.data("revise_page")
        assert len(calls) == 2 and calls[1]["error"] == PATCH_COUNT
        assert calls[1]["sections"] == [
            {"page": "rule-async-only", "heading": "Примеры", "text": examples}
        ]
        rule = s.bodies(pid)["rule-async-only"]
        assert rule == replaced(before, "Примеры", examples.replace(old, new))
        assert rule.count(new) == 2
