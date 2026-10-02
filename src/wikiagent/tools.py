"""Explicit tool contracts. Neither data nor a model response can choose an HTTP route."""

from typing import Any

from wikiagent.client import WikiClient
from wikisvc.domain.errors import WikiError
from wikisvc.tool_contracts import ALLOWLISTS, CONTRACTS, REQUIRED, definitions

__all__ = ["definitions", "execute"]


def execute(client: WikiClient, mode: str, name: str, arguments: dict[str, Any]) -> Any:
    if name not in ALLOWLISTS[mode]:
        client.forbidden_attempts += 1
        raise WikiError(
            "E_AGENT_TOOL_FORBIDDEN", "Инструмент запрещён для этой задачи.", status=403
        )
    method, route, paths, query, body = CONTRACTS[name]
    if (
        set(arguments) - {*paths, *query, *body}
        or (set(paths) | REQUIRED.get(name, set())) - arguments.keys()
    ):
        raise WikiError("E_AGENT_TOOL_ARGUMENTS", "Некорректные аргументы инструмента.")
    values = {key: arguments[key] for key in paths}
    if any(
        not isinstance(v, str) or ("/" in v and key != "path") or ".." in v or "?" in v or "%" in v
        for key, v in values.items()
    ):
        raise WikiError("E_AGENT_TOOL_ARGUMENTS", "Некорректный идентификатор.")
    options: dict[str, Any] = {}
    if query:
        options["params"] = {
            key: ",".join(arguments[key]) if isinstance(arguments[key], list) else arguments[key]
            for key in query
            if key in arguments
        }
    if body:
        options["json"] = (
            arguments["notes"]
            if name == "put_notes"
            else {key: arguments[key] for key in body if key in arguments}
        )
    return client.request(method, route.format(**values), **options)
