"""Scripted HTTP model, no live provider or network required by acceptance tests."""

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx
from jsonschema import Draft202012Validator


@dataclass(frozen=True)
class Reply:
    """A raw assistant message, for what a misbehaving model sends instead of schema JSON.

    A dict from ``respond`` is the model obeying the grammar; a Reply is everything else
    on the wire: truncated text, ``tool_calls`` in a structured task, an HTTP failure.
    """

    content: str | None = None
    tool_calls: list[dict[str, object]] | None = None
    status: int = 200


class FakeLLM:
    def __init__(
        self,
        respond: Callable[[str, dict[str, Any]], dict[str, Any] | Reply],
        *,
        check_schema: bool = False,
    ) -> None:
        self.respond = respond
        # llama.cpp constrains generation by response_format.json_schema; a fake free to
        # answer outside it tests shapes the real model can never produce.
        self.check_schema = check_schema
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.requests: list[dict[str, Any]] = []
        self.http = httpx.Client(transport=httpx.MockTransport(self.handle))

    def count(self, task: str) -> int:
        return sum(1 for name, _ in self.calls if name == task)

    def handle(self, request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        self.requests.append(payload)
        task = payload["messages"][0]["content"].split("Task: ")[-1]
        message = payload["messages"][1]["content"]
        data = json.loads(message.split("<UNTRUSTED_DATA>")[1].split("</UNTRUSTED_DATA>")[0])
        self.calls.append((task, data))
        result = self.respond(task, data)
        if isinstance(result, Reply):
            if result.status != 200:
                return httpx.Response(result.status, text="Model unavailable")
            raw: dict[str, object] = {"role": "assistant", "content": result.content}
            if result.tool_calls is not None:
                raw["tool_calls"] = result.tool_calls
            return httpx.Response(200, json={"choices": [{"message": raw}]})
        schema = (payload.get("response_format") or {}).get("json_schema")
        if self.check_schema and schema:
            errors = list(Draft202012Validator(schema["schema"]).iter_errors(result))
            if errors:
                raise AssertionError(
                    f"Fake answer to {task} breaks the grammar: "
                    + "; ".join(f"{list(e.absolute_path)}: {e.message}" for e in errors)
                )
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(result, ensure_ascii=False),
                        }
                    }
                ]
            },
        )


def claim(page_id: str = "rule-async-only", **values: Any) -> dict[str, Any]:
    return {
        "id": page_id,
        "text": "Использовать только async код Python",
        "title": "Асинхронный Python",
        "thesis": "Используй только асинхронный код в обработчиках Python.",
        "category": "architecture",
        "scopes_guess": ["lang:python"],
        "level_guess": "should",
        "aliases": ["асинхронный код", "async Python"],
        "rationale": "Синхронные операции блокируют обработку других запросов.",
        "good_example": "await client.get(url)",
        "bad_example": "requests.get(url)",
        **values,
    }


def full_claim(page_id: str = "rule-async-only", **values: object) -> dict[str, object]:
    """``claim`` with every key the strict grammar requires, defaults included."""
    return {
        **claim(page_id),
        "kind": "rule",
        "owner": None,
        "impact_terms": [],
        "ambiguous_scope": False,
        **values,
    }
