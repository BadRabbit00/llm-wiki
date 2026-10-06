from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Callable
from functools import partial
from typing import Any

from pydantic import Field, field_validator

from wikiagent.client import WikiClient
from wikiagent.models import ModelClient
from wikiagent.planner.builder import Builder
from wikiagent.planner.claims import Category, StrictModel
from wikiagent.planner.classify import Classification, verify
from wikiagent.state import AgentState
from wikisvc.domain.errors import WikiError
from wikisvc.services.extractions import normalize_quote
from wikisvc.storage.state_db import now


class Locator(StrictModel):
    unit: str = Field(pattern=r"^(стр\.|гл\.)$")
    start: int = Field(ge=1)
    end: int | None = Field(default=None, ge=1)


class BookRelation(StrictModel):
    rule_id: str
    type: str = Field(pattern=r"^(refines|conflicts_with|supersedes|depends_on)$")


class Candidate(StrictModel):
    title: str = Field(min_length=3, max_length=120)
    thesis: str = Field(min_length=20, max_length=160)
    category: Category
    applies_to_suggestion: list[str] = Field(min_length=1)
    level_suggestion: str = Field(default="should", pattern="^(idea|should)$")
    rationale: str = Field(min_length=1, max_length=4000)
    locator: Locator
    quote: str = Field(min_length=1, max_length=1000)
    aliases: list[str] = Field(min_length=2, max_length=10)
    good_example: str = Field(default="", max_length=2000)
    bad_example: str = Field(default="", max_length=2000)
    relations: list[BookRelation] = Field(default_factory=list, max_length=10)

    @field_validator("quote")
    @classmethod
    def short_quote(cls, value: str) -> str:
        if len(value.split()) > 30:
            raise ValueError("E_QUOTE_TOO_LONG: не более 30 слов")
        return value


class ChapterResult(StrictModel):
    candidates: list[Candidate] = Field(default_factory=list, max_length=10)
    state_summary: str = Field(default="", max_length=3750)
    open_references: list[str] = Field(default_factory=list, max_length=20)


class Merge(StrictModel):
    keep: str
    drop: str


class Link(StrictModel):
    src: str
    target: str
    rel: str = Field(pattern=r"^(refines|conflicts_with|supersedes|depends_on)$")


class KeyIdea(StrictModel):
    id: str
    text: str = Field(max_length=160)


class BookReview(StrictModel):
    merge: list[Merge] = Field(default_factory=list, max_length=20)
    links: list[Link] = Field(default_factory=list, max_length=30)
    key_ideas: list[KeyIdea] = Field(default_factory=list, max_length=15)


class IngestBook:
    def __init__(
        self,
        client: WikiClient,
        models: ModelClient,
        state: AgentState,
        checkpoint: Callable[[str], None] | None = None,
    ) -> None:
        self.client, self.models, self.state = client, models, state
        self.builder = Builder(client, models)
        self.boundary = checkpoint or (lambda job_id: None)

    def context(self, value: dict[str, Any]) -> dict[str, Any]:
        budget = int(self.models.config.limits.state_tokens * 2.5)
        while len(json.dumps(value, ensure_ascii=False)) > budget:
            if value.get("open_references"):
                value["open_references"].pop()
            elif value.get("titles"):
                value["titles"].pop(0)
            else:
                value["summary"] = value.get("summary", "")[: max(0, budget - 200)]
                break
        return value

    def proposal(self, job_id: str, payload: dict[str, Any]) -> str:
        saved = self.state.restore(job_id, "proposal")
        if saved:
            return str(saved)
        marker = "Job " + job_id
        # Recover a create response lost before the local checkpoint.
        for existing in self.client.all("/proposals", kind="book"):
            if marker in existing["description"]:
                pid = existing["pid"]
                break
        else:
            pid = self.client.request(
                "POST",
                "/proposals",
                json={
                    "kind": "book",
                    "title": ("Книга: " + payload.get("title", "Новый источник"))[:200],
                    "description": self.builder.description(marker),
                },
            )["pid"]
        self.state.checkpoint(job_id, "proposal", pid)
        return str(pid)

    def candidate_id(self, job_id: str, pid: str, candidate: Candidate, identity: str) -> str:
        from wikisvc.services.raw import safe_name

        allocated: dict[str, str] = self.state.restore(job_id, "candidate_ids", {})
        if identity in allocated:
            return allocated[identity]
        draft = self.client.request("GET", "/proposals/" + pid)["pages"]
        # Recover jobs made before the readable-ID migration as well as a lost write response.
        same = next(
            (
                p["id"]
                for p in draft
                if p["type"] == "rule"
                and normalize_quote(p["summary"]) == normalize_quote(candidate.thesis)
            ),
            None,
        )
        if same:
            page_id = str(same)
        else:
            slug = (
                re.sub(r"[^a-z0-9]+", "-", safe_name(candidate.thesis).lower())
                .strip("-")[:60]
                .rstrip("-")
                or identity
            )
            base = "rule-" + candidate.category + "-" + slug
            used = (
                {
                    p["id"]
                    for p in self.client.all("/rules", lifecycle="candidate,active,deprecated")
                }
                | {p["id"] for p in draft}
                | set(allocated.values())
            )
            page_id, suffix = base, 2
            while page_id in used:
                page_id = base + "-" + str(suffix)
                suffix += 1
        allocated[identity] = page_id
        self.state.checkpoint(job_id, "candidate_ids", allocated)
        return page_id

    def run(self, job_id: str, payload: dict[str, Any]) -> None:
        path = payload["raw_path"]
        status = self.client.request("POST", "/raw/" + path + "/extract")
        deadline = time.monotonic() + self.models.config.models["planner"].timeout_seconds + 600
        while status["status"] != "done":
            self.boundary(job_id)
            if status["status"] == "failed":
                raise WikiError(
                    status.get("error") or "E_EXTRACT_FAILED", "Не удалось извлечь книгу."
                )
            if time.monotonic() > deadline:
                raise WikiError("E_EXTRACT_TIMEOUT", "Ожидание извлечения превысило лимит.")
            time.sleep(0.1)
            status = self.client.request("POST", "/raw/" + path + "/extract")
        outline = self.client.request("GET", "/raw/" + path + "/outline")
        if outline["origin"] == "fallback":
            self.state.status(
                job_id,
                "needs_outline",
                {"reason": "Уточните оглавление через PUT /raw/{path}/outline"},
            )
            return
        pid = self.proposal(job_id, payload)
        existing_proposal = self.client.request("GET", "/proposals/" + pid)
        if existing_proposal["status"] in ("submitted", "accepted"):
            report = self.state.restore(
                job_id,
                "report",
                {
                    "proposal": pid,
                    "candidates": len(self.state.restore(job_id, "candidates", {})),
                    "chapters_done": self.state.restore(job_id, "chapter_done", 0),
                },
            )
            self.state.status(
                job_id,
                "done" if existing_proposal["status"] == "accepted" else "awaiting_review",
                report,
            )
            return
        source = "src-book-" + job_id[:12]
        source_metadata = {
            "id": source,
            "type": "source",
            "kind": "book",
            "title": payload.get("title") or "Книга " + job_id[:12],
            "summary": "Идеи и краткие цитаты книги для проверки правил команды.",
            "raw_path": path,
            "raw_sha256": status["sha256"],
            "ingested_at": now(),
            **{k: str(payload[k]) for k in ("author", "year") if payload.get(k) is not None},
        }
        source_body = "## Кратко\n\nКнига обработана по главам; кандидаты требуют решения человека.\n\n## Ключевые факты\n\nКраткие идеи будут дополнены после проверки.\n\n## Что изменилось в вики\n\nСозданы инертные кандидаты правил."
        if not self.state.restore(job_id, "source_written", False):
            self.builder.put(pid, source, source_metadata, source_body)
            self.state.checkpoint(job_id, "source_written", True)
        vocabulary = self.client.request("GET", "/scopes")
        retired = {
            normalize_quote(p["summary"]) for p in self.client.all("/rules", lifecycle="deprecated")
        }
        done = int(self.state.restore(job_id, "chapter_done", 0))
        candidates: dict[str, Any] = self.state.restore(job_id, "candidates", {})
        errors: list[dict[str, Any]] = self.state.restore(job_id, "errors", [])
        context = self.state.restore(job_id, "context", {})
        for chapter in outline["chapters"]:
            if chapter["n"] <= done:
                continue
            self.boundary(job_id)
            offset = 0
            chunk_pages = None
            summary = ""
            open_refs = []
            while True:
                self.boundary(job_id)
                text = self.client.request(
                    "GET",
                    "/raw/" + path + "/text",
                    params={
                        **(
                            {"pages": chunk_pages, "offset": offset}
                            if chunk_pages
                            else {"chapter": chapter["n"]}
                        ),
                        "max_chars": min(
                            60000, int(self.models.config.limits.chapter_chunk_tokens * 2.5)
                        ),
                    },
                )
                key = f"chapter:{chapter['n']}:{chunk_pages or 'start'}:{offset}"
                output = self.state.restore(job_id, key)
                related = self.client.request(
                    "GET",
                    "/rules/related",
                    params={"q": (chapter["title"] + " " + text["text"])[:1000], "limit": 8},
                )
                known = {r["id"] for r in related["rules"]}
                if output is None:

                    def valid(result: ChapterResult, known: set[str] = known) -> None:
                        for candidate in result.candidates:
                            if set(candidate.applies_to_suggestion) - set(vocabulary) - {"*"}:
                                raise WikiError("E_SCOPE_UNKNOWN", "Область отсутствует в словаре.")
                            if any(r.rule_id not in known for r in candidate.relations):
                                raise WikiError(
                                    "E_LINK_UNRESOLVED", "Связь отсутствует в полученном контексте."
                                )
                            locator = candidate.locator
                            if locator.unit == "гл.":
                                excerpt = self.client.request(
                                    "GET",
                                    "/raw/" + path + "/text",
                                    params={"chapter": locator.start, "max_chars": 60000},
                                )["text"]
                            else:
                                end = locator.end or locator.start
                                if not 1 <= locator.start <= end <= status["pages"]:
                                    raise WikiError(
                                        "E_LOCATOR_OUT_OF_RANGE", "Страницы отсутствуют."
                                    )
                                excerpt = self.client.request(
                                    "GET",
                                    "/raw/" + path + "/text",
                                    params={
                                        "pages": f"{max(1, locator.start - 1)}-{min(status['pages'], end + 1)}",
                                        "max_chars": 60000,
                                    },
                                )["text"]
                            if normalize_quote(candidate.quote) not in normalize_quote(excerpt):
                                raise WikiError(
                                    "E_QUOTE_NOT_FOUND",
                                    "Цитата отсутствует на указанных страницах.",
                                )

                    try:
                        generated = self.models.structured(
                            "planner",
                            "book_chapter",
                            ChapterResult,
                            {
                                "chapter": chapter,
                                "text": text["text"],
                                "pages": text["pages"],
                                "state": context,
                                "scopes_hint": payload.get("scopes_hint", []),
                                "scopes": vocabulary,
                                "related": related,
                                "unit": "гл." if path.endswith(".epub") else "стр.",
                            },
                            valid,
                        )
                        output = generated.model_dump()
                    except WikiError as exc:
                        errors.append({"chapter": chapter["n"], "code": exc.code})
                        output = ChapterResult().model_dump()
                    self.state.checkpoint(job_id, key, output)
                generated = ChapterResult.model_validate(output)
                for candidate in generated.candidates:
                    if normalize_quote(candidate.thesis) in retired:
                        errors.append(
                            {
                                "chapter": chapter["n"],
                                "code": "SKIP_DEPRECATED",
                                "thesis": candidate.thesis,
                            }
                        )
                        continue
                    identity = hashlib.sha256(
                        normalize_quote(candidate.thesis).encode()
                    ).hexdigest()[:12]
                    page_id = self.candidate_id(job_id, pid, candidate, identity)
                    relations: dict[str, list[str]] = {}
                    for relation in candidate.relations:
                        relations.setdefault(relation.type, []).append(relation.rule_id)
                    if known:
                        classification_key = "classification:" + identity
                        saved = self.state.restore(job_id, classification_key)
                        if saved is None:
                            documents = {
                                target: self.client.request("GET", "/pages/" + target)
                                for target in known
                            }
                            classified = self.models.structured(
                                "planner",
                                "classify",
                                Classification,
                                {
                                    "claim": {"text": candidate.thesis, "id": page_id},
                                    "pages": list(documents.values()),
                                },
                                partial(verify, pages=documents),
                            )
                            saved = classified.model_dump()
                            self.state.checkpoint(job_id, classification_key, saved)
                        classified = Classification.model_validate(saved)
                        if any(r.relation == "duplicate_of" for r in classified.relations):
                            errors.append(
                                {
                                    "chapter": chapter["n"],
                                    "code": "SKIP_DUPLICATE",
                                    "thesis": candidate.thesis,
                                }
                            )
                            continue
                        for classified_link in classified.relations:
                            if classified_link.target and classified_link.relation in (
                                "refines",
                                "conflicts_with",
                                "supersedes",
                            ):
                                targets = relations.setdefault(classified_link.relation, [])
                                if classified_link.target not in targets:
                                    targets.append(classified_link.target)
                    locator = candidate.locator
                    location = str(locator.start) + (
                        ("-" + str(locator.end))
                        if locator.end and locator.end != locator.start
                        else ""
                    )
                    quote = candidate.quote.replace('"', "“")
                    body = f'## Правило\n\n{candidate.thesis}\n\n## Обоснование\n\n{candidate.rationale}\n\n[@{source} {locator.unit} {location} "{quote}"]\n\n## Примеры\n\nПримеры предложены моделью, проверьте.\n\nТак:\n\n{candidate.good_example}\n\nНе так:\n\n{candidate.bad_example}'
                    metadata = {
                        "id": page_id,
                        "type": "rule",
                        "title": candidate.title,
                        "summary": candidate.thesis,
                        "category": candidate.category,
                        "origin": "book",
                        "applies_to": candidate.applies_to_suggestion,
                        "aliases": candidate.aliases,
                        "sources": [source],
                        "relations": relations,
                    }
                    try:
                        self.builder.put(pid, page_id, metadata, body)
                        candidates[page_id] = {
                            "id": page_id,
                            "title": candidate.title,
                            "summary": candidate.thesis,
                            "relations": relations,
                            "chapter": chapter["n"],
                        }
                    except WikiError as exc:
                        errors.append(
                            {"chapter": chapter["n"], "code": exc.code, "thesis": candidate.thesis}
                        )
                    self.state.checkpoint(job_id, "candidates", candidates)
                summary = generated.state_summary
                open_refs = generated.open_references
                context = self.context(
                    {
                        "summary": summary,
                        "titles": [c["title"] for c in candidates.values()],
                        "open_references": open_refs,
                    }
                )
                if not text["next_pages"]:
                    break
                chunk_pages, offset = text["next_pages"], text["next_offset"]
            context = self.context(
                {
                    "summary": summary,
                    "titles": [c["title"] for c in candidates.values()],
                    "open_references": open_refs,
                }
            )
            self.state.checkpoint(job_id, "context", context)
            self.state.checkpoint(job_id, "errors", errors)
            self.state.checkpoint(job_id, "chapter_done", chapter["n"])
            self.state.status(
                job_id,
                "running",
                {
                    "chapters_done": chapter["n"],
                    "chapters_total": len(outline["chapters"]),
                    "candidates": len(candidates),
                    "errors": errors,
                    "proposal": pid,
                },
            )
        self.boundary(job_id)
        key_ideas: list[KeyIdea] = []
        items = list(candidates.values())
        for start in range(0, len(items), 40):
            self.boundary(job_id)
            review_key = f"review:{start}"
            stored = self.state.restore(job_id, review_key)
            if stored is None:
                result = self.models.structured(
                    "reviewer",
                    "book_review",
                    BookReview,
                    {"candidates": items[start : start + 40], "state": context, "outline": outline},
                )
                stored = result.model_dump()
                self.state.checkpoint(job_id, review_key, stored)
            review = BookReview.model_validate(stored)
            for merge in review.merge:
                if (
                    merge.keep not in candidates
                    or merge.drop not in candidates
                    or merge.keep == merge.drop
                ):
                    continue
                draft = {
                    p["id"]: p for p in self.client.request("GET", "/proposals/" + pid)["pages"]
                }
                if merge.drop in draft:
                    # Preserve the rejected duplicate's evidence on the survivor, then
                    # redirect references before removing the redundant candidate.
                    dropped = draft[merge.drop]
                    marker = "Объединён кандидат " + merge.drop
                    if marker not in draft[merge.keep]["body_md"]:
                        self.client.request(
                            "PATCH",
                            f"/proposals/{pid}/pages/{merge.keep}",
                            json={
                                "ops": [
                                    {
                                        "op": "append_to_section",
                                        "heading": "Обоснование",
                                        "text": marker
                                        + "\n\n"
                                        + re.sub(r"(?m)^## (.+)$", r"**\1**", dropped["body_md"]),
                                    }
                                ]
                            },
                        )
                    for page in draft.values():
                        operations = []
                        for rel, targets in page.get("relations", {}).items():
                            if merge.drop in targets:
                                operations.append(
                                    {"op": "remove_relation", "rel": rel, "target": merge.drop}
                                )
                                if page["id"] != merge.keep:
                                    operations.append(
                                        {"op": "add_relation", "rel": rel, "target": merge.keep}
                                    )
                        if operations:
                            self.client.request(
                                "PATCH",
                                f"/proposals/{pid}/pages/{page['id']}",
                                json={"ops": operations},
                            )
                    self.client.request("DELETE", f"/proposals/{pid}/pages/{merge.drop}")
                candidates.pop(merge.drop, None)
                self.state.checkpoint(job_id, "candidates", candidates)
            for link in review.links:
                if link.src not in candidates or link.target not in candidates:
                    raise WikiError(
                        "E_LINK_UNRESOLVED", "Второй проход должен связывать кандидатов этой книги."
                    )
                self.client.request(
                    "PATCH",
                    f"/proposals/{pid}/pages/{link.src}",
                    json={"ops": [{"op": "add_relation", "rel": link.rel, "target": link.target}]},
                )
            key_ideas.extend(idea for idea in review.key_ideas if idea.id in candidates)
        if not key_ideas:
            key_ideas = [
                KeyIdea(id=c["id"], text=c["summary"]) for c in list(candidates.values())[:15]
            ]
        source_body += "\n\n## Ключевые идеи\n\n" + "\n".join(
            f"- [[{idea.id}]]: {idea.text}" for idea in key_ideas[:15]
        )
        self.builder.put(pid, source, source_metadata, source_body)
        self.builder.validate(pid)
        self.boundary(job_id)
        self.client.request("POST", f"/proposals/{pid}/submit")
        report = {
            "proposal": pid,
            "chapters_done": len(outline["chapters"]),
            "chapters_total": len(outline["chapters"]),
            "candidates": len(candidates),
            "errors": errors,
            "conflicts": [
                c["id"] for c in candidates.values() if c["relations"].get("conflicts_with")
            ],
        }
        self.state.checkpoint(job_id, "report", report)
        self.state.status(job_id, "awaiting_review", report)
