"""Scripted HTTP model, no live provider or network required by acceptance tests."""

import json
from collections.abc import Callable
from typing import Any

import httpx


class FakeLLM:
    def __init__(self, respond: Callable[[str, dict[str, Any]], dict[str, Any]]) -> None:
        self.respond = respond
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.http = httpx.Client(transport=httpx.MockTransport(self.handle))

    def handle(self, request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        task = payload["messages"][0]["content"].split("Task: ")[-1]
        message = payload["messages"][1]["content"]
        data = json.loads(message.split("<UNTRUSTED_DATA>")[1].split("</UNTRUSTED_DATA>")[0])
        self.calls.append((task, data))
        result = self.respond(task, data)
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
