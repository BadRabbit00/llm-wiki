from __future__ import annotations

import hashlib
import json
import math
import re
from copy import deepcopy
from pathlib import Path
from typing import TYPE_CHECKING, Any

from wikisvc.domain.errors import WikiError
from wikisvc.domain.models import Page, Principal
from wikisvc.domain.validate import overlaps
from wikisvc.services.auth import can_read
from wikisvc.storage.safefs import SafeFS

if TYPE_CHECKING:
    from wikisvc.services.runtime import Runtime


class Policies:
    def __init__(self, runtime: Runtime) -> None:
        self.rt = runtime
        self.cache: dict[str, dict[str, Any]] = {}
        self.generation = ""

    def tokens(self, text: str) -> int:
        return sum(
            math.ceil(len(line) / self.rt.settings.chars_per_token)
            for line in text.splitlines(keepends=True)
        )

    def compile(
        self,
        actor: Principal,
        profile: str | None = None,
        scopes: list[str] | None = None,
        budget_tokens: int | None = None,
        enforced: str = "keep_must",
        explain: bool = False,
        count_usage: bool = True,
    ) -> dict[str, Any]:
        registry = self.rt.registry
        if profile and scopes is not None:
            raise WikiError("E_REQUEST_INVALID", "Укажите профиль или явные scopes.", status=400)
        if profile and profile not in registry.profiles:
            raise WikiError("E_PROFILE_UNKNOWN", "Профиль не найден.", status=404)
        definition = registry.profiles.get(profile or "")
        selected_scopes = sorted(set(definition.scopes if definition else scopes or []))
        if not selected_scopes or any(s not in registry.scopes for s in selected_scopes):
            raise WikiError("E_SCOPE_UNKNOWN", "Нужны известные области проекта.", status=400)
        budget = (
            budget_tokens
            if budget_tokens is not None
            else definition.budget_tokens
            if definition
            else 2000
        )
        if not 1 <= budget <= 100000 or enforced not in {"keep_must", "all", "none"}:
            raise WikiError("E_REQUEST_INVALID", "Некорректный бюджет или enforced.", status=400)
        fs = SafeFS(self.rt.settings.wiki_root)
        path = "schema/policy-template.md"
        template = (
            fs.read(path)
            if fs.path(path).exists()
            else SafeFS(Path(__file__).resolve().parents[1] / "template").read(path)
        )
        parameters = {
            "profile": profile,
            "scopes": selected_scopes,
            "budget_tokens": budget,
            "enforced": enforced,
            "chars_per_token": self.rt.settings.chars_per_token,
            "category_order": self.rt.settings.policy_category_order,
            "template": template,
        }
        with self.rt.index.connect() as db:
            stamp = db.execute("SELECT value FROM meta WHERE key='generation'").fetchone()
        generation = str(stamp[0]) if stamp else ""
        if generation != self.generation:
            self.cache.clear()
            self.generation = generation
        key = json.dumps([parameters, actor.clearance, explain], sort_keys=True, ensure_ascii=False)
        if key not in self.cache:
            pages = [
                p
                for p in self.rt.indexer.pages()
                if p.frontmatter.type == "rule" and can_read(actor, p.frontmatter.sensitivity)
            ]
            self.cache[key] = self._compile(pages, parameters, explain)
            if len(self.cache) > 128:
                self.cache.pop(next(iter(self.cache)))
        result = deepcopy(self.cache[key])
        if count_usage:
            self.rt.state.usage([item["id"] for item in result["included"]], "delivered")
        return result

    def _compile(
        self, pages: list[Page], parameters: dict[str, Any], explain: bool
    ) -> dict[str, Any]:
        candidates, omitted = [], []
        counts: dict[str, int] = {}
        order = parameters["category_order"].split(",")
        for page in pages:
            data = page.frontmatter.model_extra or {}
            enforcers = [x for x in data.get("enforced_by", []) if x != "none"]
            reason = None
            if not overlaps(data.get("applies_to", []), parameters["scopes"]):
                reason = "scope"
            elif data.get("lifecycle") != "active" or not page.frontmatter.verified_by:
                reason = "lifecycle"
            elif data.get("level") not in ("must", "should"):
                reason = "level"
            elif enforcers and (
                parameters["enforced"] == "none"
                or (parameters["enforced"] == "keep_must" and data.get("level") != "must")
            ):
                reason = "enforced"
            if reason:
                counts[reason] = counts.get(reason, 0) + 1
                if explain or reason == "enforced":
                    omitted.append({"id": page.id, "reason": reason})
                continue
            candidates.append(page)
        candidates.sort(
            key=lambda p: (
                (p.frontmatter.model_extra or {}).get("level") != "must",
                -(p.frontmatter.model_extra or {}).get("priority", 3),
                order.index((p.frontmatter.model_extra or {}).get("category"))
                if (p.frontmatter.model_extra or {}).get("category") in order
                else len(order),
                p.id,
            )
        )
        included: list[Page] = []
        for page in candidates:
            trial = [*included, page]
            if (page.frontmatter.model_extra or {}).get("level") == "must" or self._render(
                trial, parameters
            )[1] <= parameters["budget_tokens"]:
                included.append(page)
            else:
                omitted.append({"id": page.id, "reason": "budget"})
                counts["budget"] = counts.get("budget", 0) + 1
        markdown, used, version = self._render(included, parameters)
        return {
            "profile": parameters["profile"],
            "scopes": parameters["scopes"],
            "budget_tokens": parameters["budget_tokens"],
            "used_tokens": used,
            "version": version,
            "over_budget": used > parameters["budget_tokens"],
            "markdown": markdown,
            "included": [
                {
                    "id": p.id,
                    "level": (p.frontmatter.model_extra or {})["level"],
                    "category": (p.frontmatter.model_extra or {})["category"],
                    "tokens": self.tokens(self._line(p)),
                }
                for p in included
            ],
            "omitted": sorted(omitted, key=lambda x: x["id"]),
            "omitted_counts": counts,
        }

    @staticmethod
    def _line(page: Page) -> str:
        data = page.frontmatter.model_extra or {}
        enforcers = [x for x in data.get("enforced_by", []) if x != "none"]
        checked = " (проверяется: " + ", ".join(enforcers) + ")" if enforcers else ""
        return f"- [{data['level'].upper()}] {page.frontmatter.summary}{checked} → {page.id}\n"

    def _render(self, pages: list[Page], parameters: dict[str, Any]) -> tuple[str, int, str]:
        version = hashlib.sha256(
            json.dumps(
                [sorted((p.id, p.version) for p in pages), parameters],
                sort_keys=True,
                ensure_ascii=False,
            ).encode()
        ).hexdigest()[:8]
        groups = []
        for level, title in (("must", "Обязательные"), ("should", "Желательные")):
            lines = "".join(
                self._line(p)
                for p in pages
                if (p.frontmatter.model_extra or {}).get("level") == level
            )
            if lines:
                groups.append(title + ":\n" + lines.rstrip())
        values = {
            "profile": parameters["profile"] or ", ".join(parameters["scopes"]),
            "version": version,
            "rules": "\n\n".join(groups),
            "used_tokens": "0",
        }
        markdown = ""
        for _ in range(10):
            markdown = parameters["template"]
            for name, value in values.items():
                markdown = markdown.replace("{" + name + "}", value)
            used = self.tokens(markdown)
            if str(used) == values["used_tokens"]:
                break
            values["used_tokens"] = str(used)
        return markdown, self.tokens(markdown), version


BLOCK = re.compile(
    r"<!-- wikisvc:begin version=([a-f0-9]{8}) -->.*?<!-- wikisvc:end -->", re.DOTALL
)


def export_block(path: Path, compiled: dict[str, Any]) -> None:
    current = path.read_text() if path.exists() else ""
    block = f"<!-- wikisvc:begin version={compiled['version']} -->\n{compiled['markdown'].rstrip()}\n<!-- wikisvc:end -->"
    if (
        current.count("<!-- wikisvc:begin") != len(BLOCK.findall(current))
        or len(BLOCK.findall(current)) > 1
    ):
        raise WikiError("E_POLICY_BLOCK", "Повреждён или неоднозначен блок wikisvc.")
    updated = (
        BLOCK.sub(lambda _: block, current)
        if BLOCK.search(current)
        else current + ("\n\n" if current else "") + block + "\n"
    )
    SafeFS(path.resolve().parent).write(path.name, updated)
