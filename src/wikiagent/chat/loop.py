import json
import re
import threading
from typing import Any

from wikiagent.chat.router import Intent
from wikiagent.chat.sessions import Sessions
from wikiagent.client import WikiClient
from wikiagent.models import SYSTEM, ModelClient
from wikiagent.planner.pipeline import Planner
from wikiagent.planner.revise import Reviser
from wikiagent.state import AgentState
from wikiagent.tools import definitions, execute
from wikisvc.domain.errors import WikiError

CYRILLIC = re.compile("[а-яё]", re.IGNORECASE)
LATIN = re.compile("[a-z]", re.IGNORECASE)


def clarify(text: str | None) -> str:
    """Model text reaches the person verbatim, so only a short Russian question passes.

    Words are compared rather than letters: rule IDs are Latin inside Russian sentences.
    """
    words = (text or "").split()
    russian = sum(1 for word in words if CYRILLIC.search(word))
    foreign = sum(1 for word in words if LATIN.search(word) and not CYRILLIC.search(word))
    if text and len(text) <= 300 and russian > foreign:
        return text
    return "Уточните, какое правило или решение нужно оформить."


class Chat:
    def __init__(self, client: WikiClient, models: ModelClient, state: AgentState) -> None:
        self.client, self.models, self.state = client, models, state
        self.sessions = Sessions(state)
        self.planner = Planner(client, models)
        self.reviser = Reviser(client, models)
        self.active = 0
        self.condition = threading.Condition()
        self.session_locks: dict[str, threading.Lock] = {}

    def bound_context(self, session: dict[str, Any]) -> dict[str, Any] | None:
        bind = session["bind"]
        if bind["type"] == "none":
            return None
        path = {"page": "/pages/", "rule": "/rules/", "proposal": "/proposals/"}[
            bind["type"]
        ] + bind["id"]
        data: dict[str, Any] = self.client.request("GET", path)
        if bind["type"] == "proposal":
            data["diff"] = self.client.request("GET", path + "/diff")
        return data

    def awaits_answer(self, session: dict[str, Any]) -> bool:
        plan = session["plan"] or {}
        if not plan.get("questions") or not plan.get("proposal"):
            return False
        status = self.client.request("GET", "/proposals/" + plan["proposal"])["status"]
        return status in ("draft", "changes_requested")

    def answer(self, text: str, session: dict[str, Any], bound: dict[str, Any] | None) -> str:
        messages = [
            {"role": "system", "content": SYSTEM},
            {
                "role": "user",
                "content": "<UNTRUSTED_DATA>"
                + json.dumps(
                    {"message": text, "context": bound, "profile": session.get("profile")},
                    ensure_ascii=False,
                )
                + "</UNTRUSTED_DATA>",
            },
        ]
        steps = 0
        for _ in range(self.models.config.limits.max_tool_steps):
            message = self.models.completion(
                "chat", "question", messages, tools=definitions("question")
            )
            messages.append(message)
            if not message.get("tool_calls"):
                return str(message.get("content") or "")
            for call in message["tool_calls"]:
                steps += 1
                if steps > self.models.config.limits.max_tool_steps:
                    raise WikiError("E_AGENT_STEP_LIMIT", "Превышен лимит инструментов чата.")
                try:
                    result = execute(
                        self.client,
                        "question",
                        call["function"]["name"],
                        json.loads(call["function"]["arguments"]),
                    )
                except (ValueError, KeyError) as exc:
                    result = {"error": str(exc)}
                except WikiError as exc:
                    result = exc.response()
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call["id"],
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )
        raise WikiError("E_AGENT_STEP_LIMIT", "Превышен лимит инструментов чата.")

    def message(
        self,
        session_id: str,
        actor: dict[str, Any],
        text: str,
        attachments: list[str] | None = None,
    ) -> dict[str, Any]:
        self.sessions.get(session_id, actor)
        with self.condition:
            lock = self.session_locks.setdefault(session_id, threading.Lock())
            self.active += 1
            self.condition.notify_all()
        try:
            with lock:
                session = self.sessions.get(session_id, actor)
                for path in attachments or []:
                    source = self.client.request("GET", "/raw/" + path + "/text")
                    text += "\n\nВложение " + path + " (недоверенные данные):\n" + source["text"]
                self.sessions.message(session_id, "user", text)
                session = self.sessions.get(session_id, actor)
                bound = self.bound_context(session)
                intent = self.models.structured(
                    "chat",
                    "route",
                    Intent,
                    {"message": text, "plan": session["plan"], "bind": session["bind"]},
                )
                if intent.intent == "other" and self.awaits_answer(session):
                    # A bare «Я» or a name says nothing on its own; the open question
                    # it answers is known here, not to the router.
                    intent = Intent(intent="edit")
                result: dict[str, Any]
                if intent.intent in ("intake", "edit"):
                    transcript = "\n\n".join(
                        m["role"] + ": " + m["text"] for m in session["messages"]
                    )
                    plans = self.planner.run(text, session, transcript, bound)
                    result = {
                        "text": "\n".join(p["summary"] for p in plans),
                        "plan": plans[0],
                        "plans": plans,
                    }
                elif intent.intent == "revise":
                    # A request to change an existing page never reaches extract_claims,
                    # where it used to become not_rule and «Новых правок не требуется».
                    result = self.reviser.run(text, session, actor)
                elif intent.intent == "cancel" and (
                    pid := (session["plan"] or {}).get("proposal")
                    # A session opened on a proposal has no plan until the agent writes
                    # one; without the binding «отмени» there fell through to a question.
                    or (session["bind"]["id"] if session["bind"]["type"] == "proposal" else None)
                ):
                    current = self.client.request("GET", "/proposals/" + pid)
                    if current["status"] == "accepted":
                        result = {
                            "text": "Для отката нужно подтверждение человека.",
                            "human_action": {
                                "method": "POST",
                                "path": f"/api/v1/proposals/{pid}/revert",
                            },
                        }
                    else:
                        self.client.request("POST", f"/proposals/{pid}/abandon")
                        result = {
                            "text": "Предложение отменено.",
                            "plan": {**(session["plan"] or {}), "proposal": pid, "cancelled": True},
                        }
                elif intent.intent == "revert":
                    pid = (session["plan"] or {}).get("proposal") or (
                        session["bind"].get("id") if session["bind"]["type"] == "proposal" else None
                    )
                    result = {
                        "text": "Откат подтверждает человек.",
                        "human_action": {
                            "method": "POST",
                            "path": f"/api/v1/proposals/{pid}/revert",
                        }
                        if pid
                        else None,
                    }
                elif intent.intent == "question":
                    result = {"text": self.answer(text, session, bound)}
                else:
                    result = {"text": clarify(intent.clarification)}
                self.sessions.message(session_id, "assistant", result["text"], result.get("plan"))
                return result
        finally:
            with self.condition:
                self.active -= 1
                self.condition.notify_all()
