import os
import re
from typing import Any

import httpx

from wikiagent.config import ServiceConfig
from wikisvc.domain.errors import WikiError


class WikiClient:
    """A transport allowlist, independent of model prompts and tool descriptions."""

    def __init__(self, config: ServiceConfig, http: httpx.Client | None = None) -> None:
        self.config = config
        self.http = http or httpx.Client(
            base_url=config.base_url, timeout=60, follow_redirects=False
        )
        self.forbidden_attempts = 0

    def request(self, method: str, path: str, *, token: str | None = None, **kwargs: Any) -> Any:
        method = method.upper()
        reads = r"/(?:whoami|context/[^?]+|pages(?:/[^?]*)?|rules(?:/[^?]*)?|policies/compile|profiles|scopes|search|graph/[^?]+|proposals(?:/[^?]*)?|schema(?:/[^?]*)?|raw(?:/[^?]*)?|sources/pending|findings(?:/[^?]*)?|lint(?:/[^?]*)?)"
        writes = {
            "POST": r"/(?:proposals|proposals/[a-f0-9]+/(?:submit|abandon)|raw|raw/[^?]+/extract|findings)",
            "PUT": r"/proposals/[a-f0-9]+/(?:pages/[a-z0-9-]+|notes)",
            "PATCH": r"/proposals/[a-f0-9]+/pages/[a-z0-9-]+",
            "DELETE": r"/proposals/[a-f0-9]+/pages/[a-z0-9-]+",
        }
        if not re.fullmatch(reads if method == "GET" else writes.get(method, r"(?!)"), path) or any(
            part in path.split("/")
            for part in ("accept", "promote", "deprecate", "revert", "reject", "verify")
        ):
            self.forbidden_attempts += 1
            raise WikiError(
                "E_AGENT_TOOL_FORBIDDEN",
                "Операция не входит в разрешённые инструменты агента.",
                status=403,
            )
        bearer = token if token is not None else os.environ.get(self.config.token_env, "")
        response = self.http.request(
            method, "/api/v1" + path, headers={"Authorization": "Bearer " + bearer}, **kwargs
        )
        if response.is_error:
            try:
                error = response.json()["error"]
            except (ValueError, KeyError):
                raise WikiError("E_WIKI_SERVICE", "Ошибка сервиса вики.", status=502) from None
            raise WikiError(
                error["code"],
                error["message"],
                error.get("hint", ""),
                error.get("details"),
                status=response.status_code,
            )
        return response.json()

    def check_writer(self) -> dict[str, Any]:
        actor: dict[str, Any] = self.request("GET", "/whoami")
        if actor["role"] != "writer" or actor["kind"] != "agent":
            raise WikiError(
                "E_AGENT_TOKEN", "Wikiagent требует отдельный writer-токен kind=agent.", status=403
            )
        return actor

    def whoami(self, token: str) -> dict[str, Any]:
        result: dict[str, Any] = self.request("GET", "/whoami", token=token)
        return result

    def upload_transcript(self, name: str, text: str) -> dict[str, Any]:
        result: dict[str, Any] = self.request(
            "POST",
            "/raw",
            files={"file": (name, text.encode(), "text/markdown")},
            data={"category": "transcripts"},
        )
        return result

    def all(self, path: str, **params: Any) -> list[dict[str, Any]]:
        rows = []
        cursor = None
        while True:
            result = self.request(
                "GET",
                path,
                params={**params, "limit": 100, **({"cursor": cursor} if cursor else {})},
            )
            rows.extend(result["items"])
            cursor = result["next_cursor"]
            if not cursor:
                return rows
