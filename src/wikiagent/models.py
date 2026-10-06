import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

from wikiagent.config import AgentConfig
from wikiagent.jobs.priority import PriorityGate
from wikiagent.state import AgentState
from wikisvc.domain.errors import WikiError
from wikisvc.storage.state_db import now

PROMPT_VERSION = "policy-layer-v2.1"
SYSTEM = (Path(__file__).parent / "prompts/system.md").read_text()


def strict_schema(value: Any) -> Any:
    """Require all object keys in strict outputs; optional values remain nullable."""
    if isinstance(value, list):
        return [strict_schema(item) for item in value]
    if not isinstance(value, dict):
        return value
    result = {key: strict_schema(item) for key, item in value.items() if key != "default"}
    if result.get("type") == "object" and "properties" in result:
        result["required"] = list(result["properties"])
        result["additionalProperties"] = False
    return result


class ModelClient:
    def __init__(
        self, config: AgentConfig, state: AgentState, http: httpx.Client | None = None
    ) -> None:
        self.config, self.state = config, state
        self.http = http or httpx.Client(follow_redirects=False)
        self.gate = PriorityGate()
        self.calls = 0
        self.forbidden_attempts = 0

    def completion(
        self, role: str, task: str, messages: list[dict[str, Any]], **options: Any
    ) -> dict[str, Any]:
        model = self.config.models[role]
        if len(json.dumps(messages, ensure_ascii=False)) / 2.5 > model.context - 2048:
            raise WikiError(
                "E_MODEL_CONTEXT", "Контекст модели превышен; уменьшите пакет данных.", status=400
            )
        headers = {}
        if model.token_env:
            headers["Authorization"] = "Bearer " + os.environ.get(model.token_env, "")
        with self.gate.enter(background=task.startswith("heal_")):
            with self.state.connect() as db:
                db.execute(
                    "INSERT INTO model_calls VALUES (?,?,?,?)", (now()[:10], role, task, now())
                )
            self.calls += 1
            try:
                response = self.http.post(
                    model.base_url.rstrip("/") + "/chat/completions",
                    headers=headers,
                    timeout=model.timeout_seconds,
                    json={
                        "model": model.model,
                        "temperature": model.temperature,
                        "messages": messages,
                        "max_tokens": min(4096, model.context // 4),
                        **options,
                    },
                )
                response.raise_for_status()
                result: dict[str, Any] = response.json()["choices"][0]["message"]
            except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
                raise WikiError('E_MODEL_UNAVAILABLE', 'Модель недоступна или вернула неверный ответ HTTP.', status=502) from exc
            return result

    def structured[T: BaseModel](
        self,
        role: str,
        task: str,
        schema: type[T],
        data: Any,
        validate: Callable[[T], None] | None = None,
    ) -> T:
        task_file = Path(__file__).parent / "prompts" / f"{task}.md"
        task_prompt = task_file.read_text() if task_file.is_file() else ""
        messages = [
            {"role": "system", "content": SYSTEM + "\n" + task_prompt + "\nTask: " + task},
            {
                "role": "user",
                "content": "<UNTRUSTED_DATA>\n"
                + json.dumps(data, ensure_ascii=False)
                + "\n</UNTRUSTED_DATA>",
            },
        ]
        mode = self.config.models[role].structured
        response_format: dict[str, Any] = {"type": mode}
        if mode == "json_schema":
            response_format["json_schema"] = {
                "name": schema.__name__,
                "schema": strict_schema(schema.model_json_schema()),
                "strict": True,
            }
        else:
            messages[0]["content"] += "\nJSON schema: " + json.dumps(schema.model_json_schema())
        error = ""
        for _ in range(self.config.limits.retries):
            try:
                result = self.completion(role, task, messages, response_format=response_format)
                if result.get("tool_calls"):
                    self.forbidden_attempts += len(result["tool_calls"])
                    raise ValueError("Tools are forbidden in structured planning")
                parsed = schema.model_validate_json(result.get("content") or "")
                if validate:
                    validate(parsed)
                return parsed
            except (ValidationError, ValueError, WikiError) as exc:
                error = str(exc)
                messages.append(
                    {
                        "role": "user",
                        "content": "Ошибка проверки ответа: "
                        + error[:3000]
                        + ". Верни исправленный JSON, опираясь только на исходные данные.",
                    }
                )
        raise WikiError(
            "E_MODEL_OUTPUT",
            "Модель не вернула проверяемый результат после повторов.",
            details=[{"error": error[:2000]}],
            status=422,
        )
