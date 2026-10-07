"""Deployment checks without creating sessions, jobs or proposals."""

import json
import os
from typing import Any

import httpx

from wikiagent.config import AgentConfig


def check(
    config: AgentConfig,
    *,
    dependencies_only: bool = False,
    model: bool = False,
    http: httpx.Client | None = None,
) -> list[str]:
    if http is None:
        with httpx.Client(timeout=5, follow_redirects=False, trust_env=False) as client:
            return check(config, dependencies_only=dependencies_only, model=model, http=client)

    def get(url: str, headers: dict[str, str] | None = None) -> Any:
        response = http.get(url, headers=headers)
        response.raise_for_status()
        return response.json()

    token = os.environ.get(config.wikisvc.token_env, "")
    if not token:
        raise ValueError(f"Set {config.wikisvc.token_env} to a writer kind=agent token")
    headers = {"Authorization": "Bearer " + token}
    base = config.wikisvc.base_url.rstrip("/")
    if get(base + "/api/v1/health").get("status") != "ok":
        raise ValueError("wikisvc is not ready")
    actor = get(base + "/api/v1/whoami", headers)
    if actor.get("role") != "writer" or actor.get("kind") != "agent":
        raise ValueError("wikiagent requires a writer kind=agent token")
    messages = ["wikisvc: ready; agent token: valid"]
    checked = set()
    for role, settings in config.models.items():
        key = (settings.base_url, settings.model, settings.token_env)
        if key in checked:
            continue
        checked.add(key)
        model_headers = (
            {"Authorization": "Bearer " + os.environ.get(settings.token_env, "")}
            if settings.token_env
            else {}
        )
        url = settings.base_url.rstrip("/")
        available = get(url + "/models", model_headers)
        if settings.model not in {item["id"] for item in available.get("data", [])}:
            raise ValueError(f"{role}: configured model alias is absent from /models")
        if model:
            schema = {
                "type": "object",
                "properties": {"ok": {"type": "boolean", "const": True}},
                "required": ["ok"],
                "additionalProperties": False,
            }
            response = http.post(
                url + "/chat/completions",
                headers=model_headers,
                timeout=settings.timeout_seconds,
                json={
                    "model": settings.model,
                    "messages": [{"role": "user", "content": 'Return JSON: {"ok":true}'}],
                    "temperature": 0,
                    "max_tokens": 128,
                    "response_format": (
                        {
                            "type": "json_schema",
                            "json_schema": {"name": "smoke", "strict": True, "schema": schema},
                        }
                        if settings.structured == "json_schema"
                        else {"type": "json_object"}
                    ),
                },
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            parsed = json.loads(content)
            if parsed != {"ok": True} or parsed["ok"] is not True:
                raise ValueError(f"{role}: structured generation smoke test failed")
        messages.append(
            f"{role} model: ready" + ("; structured generation: passed" if model else "")
        )
    if not dependencies_only:
        host = config.bind_host
        if host in {"0.0.0.0", "::"}:
            host = "127.0.0.1" if host == "0.0.0.0" else "::1"
        if ":" in host:
            host = f"[{host}]"
        get(f"http://{host}:{config.bind_port}/jobs", headers)
        messages.append("wikiagent: ready; authenticated API: passed")
    return messages
