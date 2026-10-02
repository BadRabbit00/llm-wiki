import hashlib
from typing import Any

from pydantic import Field

from wikiagent.client import WikiClient
from wikiagent.models import PROMPT_VERSION, ModelClient
from wikiagent.planner.claims import Claim, StrictModel
from wikisvc.domain.errors import WikiError
from wikisvc.storage.state_db import now


class Repair(StrictModel):
    id: str
    title: str | None = None
    summary: str | None = Field(default=None, min_length=20, max_length=160)
    body_md: str | None = None
    aliases: list[str] | None = None
    applies_to: list[str] | None = None


class Repairs(StrictModel):
    pages: list[Repair] = Field(max_length=10)


class Builder:
    def __init__(self, client: WikiClient, models: ModelClient) -> None:
        self.client, self.models = client, models

    def description(self, context: str) -> str:
        names = ", ".join(
            role + "=" + model.model for role, model in self.models.config.models.items()
        )
        return f"{context}\nModels: {names}\nPrompt: {PROMPT_VERSION}"

    def put(self, pid: str, page_id: str, metadata: dict[str, Any], body: str) -> dict[str, Any]:
        base = None
        try:
            base = self.client.request("GET", "/pages/" + page_id)["version"]
        except WikiError as exc:
            if exc.status != 404:
                raise
        result: dict[str, Any] = self.client.request(
            "PUT",
            f"/proposals/{pid}/pages/{page_id}",
            json={"frontmatter": metadata, "body_md": body, "base_version": base},
        )
        return result

    def source(self, pid: str, session_id: str, person: str, transcript: str) -> str:
        revision = hashlib.sha256(transcript.encode()).hexdigest()[:12]
        raw = self.client.upload_transcript(session_id + "-" + revision + ".md", transcript)
        page_id = "src-chat-" + pid[:12]
        metadata = {
            "id": page_id,
            "type": "source",
            "title": "Решения чата " + session_id[:12],
            "summary": "Решения команды из переписки, сохранённые для проверки правил.",
            "kind": "chat",
            "author": person,
            "raw_path": raw["path"],
            "raw_sha256": raw["sha256"],
            "ingested_at": now(),
        }
        body = f"## Кратко\n\nРешено в чате {now()[:10]}, автор {person}.\n\n## Ключевые факты\n\nПроверьте предложения в контексте полной переписки.\n\n## Что изменилось в вики\n\nПравила перечислены в плане предложения."
        self.put(pid, page_id, metadata, body)
        return page_id

    def apply_item(self, pid: str, item: dict[str, Any], source: str) -> None:
        action = item["action"]
        if action in ("noop_duplicate", "flag_page"):
            return
        if action == "patch_rule":
            page = self.client.request("GET", "/pages/" + item["target"])
            self.client.request(
                "PATCH",
                f"/proposals/{pid}/pages/{item['target']}",
                json={
                    "base_version": page["version"],
                    "ops": [
                        {"op": "set_field", "field": "applies_to", "value": item["scopes"]},
                        {"op": "add_source", "source": source},
                    ],
                },
            )
            return
        claim = Claim.model_validate(item["claim"])
        metadata = {
            "id": item["target"],
            "type": "rule",
            "title": claim.title,
            "summary": claim.thesis,
            "aliases": claim.aliases,
            "category": claim.category,
            "applies_to": item["scopes"],
            "origin": "team",
            "sources": [source],
            "relations": item["relations"],
        }
        body = f"## Правило\n\n{claim.thesis}\n\n## Обоснование\n\n{claim.rationale}\n\nРешение: [@{source}].\n\n## Примеры\n\nПримеры предложены моделью, проверьте.\n\nТак:\n\n{claim.good_example}\n\nНе так:\n\n{claim.bad_example}"
        self.put(pid, item["target"], metadata, body)
        for old in item["deprecate"]:
            page = self.client.request("GET", "/pages/" + old["id"])
            self.client.request(
                "PATCH",
                f"/proposals/{pid}/pages/{old['id']}",
                json={
                    "base_version": page["version"],
                    "ops": [
                        {"op": "add_source", "source": source},
                        {
                            "op": "append_to_section",
                            "heading": "Обоснование",
                            "text": f"Предложено заменить на [[{item['target']}]], решение: [@{source}].",
                        },
                    ],
                },
            )

    def validate(self, pid: str) -> dict[str, Any]:
        for attempt in range(self.models.config.limits.retries):
            result: dict[str, Any] = self.client.request("GET", f"/proposals/{pid}/validate")
            if not result["errors"]:
                return result
            if attempt + 1 == self.models.config.limits.retries:
                raise WikiError(
                    "E_AGENT_VALIDATION",
                    "Предложение требует исправлений.",
                    details=result["errors"],
                )
            proposal = self.client.request("GET", "/proposals/" + pid)
            repairs = self.models.structured(
                "planner",
                "repair_validation",
                Repairs,
                {"errors": result["errors"], "pages": proposal["pages"]},
            )
            existing = {p["id"]: p for p in proposal["pages"]}
            for repair in repairs.pages:
                if repair.id not in existing:
                    raise WikiError(
                        "E_AGENT_REPAIR", "Исправление не должно создавать новые страницы."
                    )
                page = existing[repair.id]
                metadata = {
                    k: v for k, v in page.items() if k not in ("body_md", "version", "extra")
                }
                values = repair.model_dump(exclude_none=True, exclude={"id", "body_md"})
                metadata.update(values)
                self.put(
                    pid,
                    repair.id,
                    metadata,
                    repair.body_md if repair.body_md is not None else page["body_md"],
                )
        raise AssertionError("unreachable")

    def build(
        self, plan: dict[str, Any], session: dict[str, Any], transcript: str
    ) -> dict[str, Any]:
        plan["questions"] = plan["questions"][:3]
        for n, item in enumerate(plan["items"], 1):
            item["n"] = n
        mutations = [i for i in plan["items"] if i["action"] not in ("noop_duplicate", "flag_page")]
        if not mutations:
            return {
                **plan,
                "proposal": session.get("plan", {}).get("proposal")
                if session.get("plan")
                else None,
                "summary": "Новых правок не требуется.",
            }
        pid = (session.get("plan") or {}).get("proposal")
        if pid and self.client.request("GET", "/proposals/" + pid)["status"] not in (
            "draft",
            "changes_requested",
        ):
            pid = None
        if not pid:
            pid = self.client.request(
                "POST",
                "/proposals",
                json={
                    "title": "Правила из чата " + session["id"][:12],
                    "kind": "chat",
                    "description": self.description(
                        "Session " + session["id"] + ", person " + session["owner"]
                    ),
                },
            )["pid"]
        source = self.source(pid, session["id"], session["owner"], transcript)
        for item in mutations:
            self.apply_item(pid, item, source)
        validation = self.validate(pid)
        impact = self.client.request("GET", f"/proposals/{pid}/impact")
        impacted = {p["id"]: p for p in impact["pages"]}
        for item in plan["items"]:
            if item["action"] == "flag_page":
                page = self.client.request("GET", "/pages/" + item["target"])
                impacted[page["id"]] = {k: page[k] for k in ("id", "type", "title", "summary")}
        impact["pages"] = list(impacted.values())
        promote = [
            {
                "id": i["target"],
                "level": i["level"],
                "priority": 3,
                "applies_to": i["scopes"],
                **({"owner": i["owner"]} if i.get("owner") else {}),
            }
            for i in mutations
            if i["action"] in ("create_rule", "supersede_rule")
        ]
        deprecate = [d for i in mutations for d in i.get("deprecate", [])]
        previous = session.get("plan") or {}
        if previous.get("proposal") != pid:
            previous = {}
        # A reply updates the same draft; retain earlier unresolved creations in its accept plan.
        promote_by_id = {i["id"]: i for i in previous.get("accept_body", {}).get("promote", [])}
        promote_by_id.update({i["id"]: i for i in promote})
        result = {
            **plan,
            "proposal": pid,
            "source": source,
            "validation": validation,
            "impact": impact,
            "summary": f"Предложение содержит {len(mutations)} правок; вопросов: {len(plan['questions'])}.",
            "accept_body": {"promote": list(promote_by_id.values()), "deprecate": deprecate},
            "needs_double_confirm": plan.get("touches_must", False)
            or any(i.get("level") == "must" for i in mutations)
            or len({i["target"] for i in plan["items"]}) > 5,
            "preview_diff": self.client.request("GET", f"/proposals/{pid}/diff"),
        }
        self.client.request("PUT", f"/proposals/{pid}/notes", json=result)
        return result
