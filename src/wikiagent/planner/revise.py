"""Edit the body of pages that already exist: a bound proposal, the session draft or a page.

Two model steps keep the local context small. The model first sees an outline with
headings only, then only the sections it chose. Everything it returns is checked
against what it was shown, and edits reach the service through PATCH, never PUT.
"""

import logging
import re
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from wikiagent.client import WikiClient
from wikiagent.models import ModelClient
from wikiagent.planner.builder import Builder
from wikiagent.planner.claims import StrictModel
from wikisvc.domain.errors import WikiError, not_found
from wikisvc.domain.markdown import sections
from wikisvc.domain.patch import apply_patch, section_span

EXAMPLES = "Примеры"
DISCLAIMER = "Примеры предложены моделью, проверьте."
ASK = "Уточните, что и в каком разделе изменить."
EDITABLE = ("draft", "changes_requested", "conflict")
LEVELS = ["public", "internal", "restricted"]
HEADING = re.compile(r"#{1,6}\s")


class Target(StrictModel):
    page: str
    headings: list[str] = Field(min_length=1, max_length=5)


class Located(StrictModel):
    targets: list[Target] = Field(max_length=5)


class Edit(StrictModel):
    op: Literal["replace_section", "add_section", "replace_text"]
    heading: str | None = None
    after: str | None = None
    old: str | None = None
    expect_count: int = Field(default=1, ge=1)
    text: str = Field(min_length=1, max_length=4000)

    @field_validator("text")
    @classmethod
    def no_heading(cls, value: str) -> str:
        # A heading inside the replacement would silently split or duplicate the section;
        # sections() finds the H2/H3 the service splits on, ignoring code comments.
        if HEADING.match(value.lstrip()) or any(part.heading for part in sections(value)):
            raise ValueError(
                "text не должен содержать заголовков markdown: верни только содержимое раздела"
            )
        return value

    @model_validator(mode="after")
    def addressed(self) -> "Edit":
        if self.op == "replace_text" and not self.old:
            raise ValueError("replace_text требует old")
        if self.op != "replace_text" and not self.heading:
            raise ValueError(self.op + " требует heading")
        return self


class Revision(StrictModel):
    page: str
    edits: list[Edit] = Field(min_length=1, max_length=10)
    summary: str = Field(min_length=10, max_length=160)


class Revisions(StrictModel):
    pages: list[Revision] = Field(max_length=5)


def refuse(reason: str) -> WikiError:
    return WikiError(
        "E_AGENT_REVISE_TARGET",
        "Это предложение нельзя изменить через агента.",
        "Откройте черновик из своего чата или попросите ревьюера.",
        [{"reason": reason}],
        status=409,
    )


def spans(body: str, headings: list[str]) -> dict[str, tuple[int, int]]:
    """Section content with its subsections: exactly what replace_section rewrites."""
    result = {}
    for heading in headings:
        _, start, end, _ = section_span(body, heading)
        result[heading] = (start, end)
    return result


def occurrences(body: str, old: str) -> list[int]:
    # Non-overlapping, as str.count and str.replace in the service's replace_text.
    # An empty fragment matches everywhere and would never advance; the service rejects it.
    if not old:
        return []
    found, position = [], body.find(old)
    while position != -1:
        found.append(position)
        position = body.find(old, position + len(old))
    return found


def examples(body: str) -> str | None:
    parts = [part for part in sections(body) if part.heading == EXAMPLES]
    if len(parts) != 1:
        return None
    _, start, end, _ = section_span(body, EXAMPLES)
    return body[start:end].strip()


class Reviser:
    def __init__(self, client: WikiClient, models: ModelClient) -> None:
        self.client, self.models = client, models
        self.builder = Builder(client, models)

    def readable(self, actor: dict[str, Any], pages: list[dict[str, Any]]) -> None:
        # The service hides pages above clearance as absent; the agent answers the same way.
        if any(
            LEVELS.index(page.get("sensitivity", "internal")) > LEVELS.index(actor["clearance"])
            for page in pages
        ):
            raise not_found()

    def authored(self, proposal: dict[str, Any]) -> bool:
        # The service compares identities: a person may share the agent token's display name.
        writer = self.client.check_writer()
        return bool(
            (proposal["author_identity"] or proposal["author"])
            == (writer["person"] or writer["name"])
        )

    def own(self, proposal: dict[str, Any]) -> bool:
        return bool(proposal["status"] in EDITABLE and self.authored(proposal))

    def targets(
        self, session: dict[str, Any], actor: dict[str, Any]
    ) -> tuple[str | None, list[dict[str, Any]], dict[str, Any]]:
        bind = session["bind"]
        if bind["type"] in ("rule", "page"):
            # A second edit of the same page in this session continues its open draft.
            previous = (session.get("plan") or {}).get("proposal")
            if previous:
                proposal = self.client.request("GET", "/proposals/" + previous)
                drafted = [p for p in proposal["pages"] if p["id"] == bind["id"]]
                if drafted and self.own(proposal):
                    self.readable(actor, drafted)
                    return previous, drafted, proposal.get("notes") or {}
            page: dict[str, Any] = self.client.request("GET", "/pages/" + bind["id"])
            self.readable(actor, [page])
            return None, [page], {}
        pid = (
            bind["id"]
            if bind["type"] == "proposal"
            else (session.get("plan") or {}).get("proposal")
        )
        if not pid:
            raise refuse("no_target")
        proposal = self.client.request("GET", "/proposals/" + pid)
        if proposal["status"] not in EDITABLE:
            raise refuse("state")
        # The service lets only the author edit through the agent token, so check it first.
        if not self.authored(proposal):
            raise refuse("author")
        notes: dict[str, Any] = proposal.get("notes") or {}
        if actor["role"] not in ("reviewer", "admin") and (
            not notes.get("owner") or notes["owner"] != session["owner"]
        ):
            raise refuse("owner")
        self.readable(actor, proposal["pages"])
        return pid, proposal["pages"], notes

    def current(self, pid: str | None, ids: list[str]) -> list[dict[str, Any]]:
        """Pages as they are now: the draft's copy if it has one, else the published page."""
        drafted = (
            {p["id"]: p for p in self.client.request("GET", "/proposals/" + pid)["pages"]}
            if pid
            else {}
        )
        return [
            drafted.get(page_id) or self.client.request("GET", "/pages/" + page_id)
            for page_id in ids
        ]

    def operation(
        self, edit: Edit, body: str, chosen: list[str], touched: list[str]
    ) -> dict[str, Any]:
        """Refuse anything outside the sections the model was shown."""
        heading, old = edit.heading or "", edit.old or ""  # Edit.addressed guarantees one
        if edit.op == "replace_section":
            if heading not in chosen:
                raise refuse("scope")
            touched.append(heading)
            return {"op": "replace_section", "heading": heading, "text": edit.text}
        if edit.op == "add_section":
            if edit.after is not None and edit.after not in chosen:
                raise refuse("scope")
            touched.append(heading)
            return {
                "op": "add_section",
                "heading": heading,
                "text": edit.text,
                **({"after": edit.after} if edit.after else {}),
            }
        shown = spans(body, chosen)
        for position in occurrences(body, old):
            inside = [
                name
                for name, (start, end) in shown.items()
                if start <= position and position + len(old) <= end
            ]
            if not inside:
                raise refuse("scope")
            touched.extend(inside)
        return {
            "op": "replace_text",
            "old": old,
            "new": edit.text,
            "expect_count": edit.expect_count,
        }

    def prepare(
        self,
        revisions: Revisions,
        pages: dict[str, dict[str, Any]],
        chosen: dict[str, list[str]],
    ) -> list[tuple[Revision, list[dict[str, Any]], list[str], bool]]:
        """Dry-run every edit before the first PATCH, so a failed retry leaves no partial draft."""
        result = []
        for revision in revisions.pages:
            if revision.page not in chosen:
                raise refuse("scope")
            original = body = pages[revision.page]["body_md"]
            ops: list[dict[str, Any]] = []
            touched: list[str] = []
            for edit in revision.edits:
                op = self.operation(edit, body, chosen[revision.page], touched)
                _, body = apply_patch({}, body, [op])
                ops.append(op)
            content = examples(body)
            changed = content is not None and content != examples(original)
            if changed and content is not None and DISCLAIMER not in content:
                op = {
                    "op": "replace_section",
                    "heading": EXAMPLES,
                    "text": DISCLAIMER + "\n\n" + content,
                }
                _, body = apply_patch({}, body, [op])
                ops.append(op)
            result.append((revision, ops, list(dict.fromkeys(touched)), changed))
        return result

    def base(self, page_id: str) -> str | None:
        try:
            version: str = self.client.request("GET", "/pages/" + page_id)["version"]
        except WikiError as exc:
            if exc.status != 404:
                raise
            return None
        return version

    def abandon(self, pid: str) -> None:
        try:
            self.client.request("POST", f"/proposals/{pid}/abandon")
        except WikiError as exc:
            # The original failure is what the person needs; this one goes to the log only.
            logging.getLogger(__name__).warning(
                "Could not abandon empty revision proposal %s: %s", pid, exc.code
            )

    def run(self, text: str, session: dict[str, Any], actor: dict[str, Any]) -> dict[str, Any]:
        pid, listed, notes = self.targets(session, actor)
        pages = {page["id"]: page for page in listed}
        # The published version the edits are computed against; a newer one is a conflict.
        bases = {page_id: self.base(page_id) for page_id in pages}
        outline = [
            {
                "id": page["id"],
                "type": page["type"],
                "title": page["title"],
                "summary": page["summary"],
                "headings": [part.heading for part in sections(page["body_md"]) if part.heading],
            }
            for page in listed
        ]
        located = self.models.structured(
            "planner", "locate_revision", Located, {"message": text, "pages": outline}
        )
        if not located.targets:
            return {"text": ASK}
        headings = {entry["id"]: entry["headings"] for entry in outline}
        chosen: dict[str, list[str]] = {}
        for target in located.targets:
            if target.page not in pages or set(target.headings) - set(headings[target.page]):
                raise refuse("scope")
            chosen[target.page] = list(
                dict.fromkeys([*chosen.get(target.page, []), *target.headings])
            )

        def fragments() -> list[dict[str, str]]:
            result = []
            for page_id, names in chosen.items():
                body = pages[page_id]["body_md"]
                for heading, (start, end) in spans(body, names).items():
                    result.append(
                        {"page": page_id, "heading": heading, "text": body[start:end].strip()}
                    )
            return result

        data: dict[str, Any] = {"message": text, "sections": fragments()}
        created = pid is None
        retries = self.models.config.limits.retries
        try:
            for attempt in range(retries):
                revisions = self.models.structured("planner", "revise_page", Revisions, data)
                if not revisions.pages:
                    return {"text": ASK}
                try:
                    prepared = self.prepare(revisions, pages, chosen)
                    if pid is None:
                        page_id = listed[0]["id"]
                        pid = self.client.request(
                            "POST",
                            "/proposals",
                            json={
                                "title": "Правка " + page_id + " из чата",
                                "kind": "chat",
                                "description": self.builder.description(
                                    "Session " + session["id"] + ", person " + session["owner"]
                                ),
                            },
                        )["pid"]
                    for revision, ops, _, _ in prepared:
                        self.client.request(
                            "PATCH",
                            f"/proposals/{pid}/pages/{revision.page}",
                            json={"base_version": bases[revision.page], "ops": ops},
                        )
                    break
                except WikiError as exc:
                    if (
                        exc.code not in ("E_PATCH_SECTION", "E_PATCH_COUNT")
                        or attempt + 1 == retries
                    ):
                        raise
                    # The service may have refused because the draft changed meanwhile:
                    # the retry works on the text as it is now.
                    pages = {p["id"]: p for p in self.current(pid, list(pages))}
                    bases = {page_id: self.base(page_id) for page_id in pages}
                    data = {
                        "message": text,
                        "sections": fragments(),
                        "previous": revisions.model_dump(exclude_unset=True),
                        "error": exc.message + " " + exc.hint,
                    }
            if pid is None:
                raise AssertionError("unreachable: the loop either patched a proposal or raised")
            validation = self.builder.validate(pid)
            lines = [f"Изменено: {revision.page} — {revision.summary}" for revision, *_ in prepared]
            # A new draft belongs to this session; an existing one keeps its recorded owner.
            owner = session["owner"] if created else notes.get("owner")
            plan = {
                "summary": "\n".join(lines),
                "items": [
                    {
                        "n": n,
                        "action": "revise_page",
                        "target": revision.page,
                        "headings": touched,
                        "reason": revision.summary,
                    }
                    for n, (revision, _, touched, _) in enumerate(prepared, 1)
                ],
                # Open questions gate acceptance in review; a revision does not answer them.
                "questions": notes.get("questions", []),
                "assumptions": [DISCLAIMER] if any(changed for *_, changed in prepared) else [],
                "proposal": pid,
                **({"owner": owner} if owner else {}),
                "validation": validation,
                "impact": self.client.request("GET", f"/proposals/{pid}/impact"),
                "accept_body": notes.get("accept_body") or {"promote": [], "deprecate": []},
                "needs_double_confirm": notes.get("needs_double_confirm", False)
                or any(pages[revision.page].get("level") == "must" for revision, *_ in prepared),
                "preview_diff": self.client.request("GET", f"/proposals/{pid}/diff"),
            }
            self.client.request("PUT", f"/proposals/{pid}/notes", json=plan)
        except Exception:
            # A draft opened by this call and left half-done would sit in the review queue.
            if created and pid is not None:
                self.abandon(pid)
            raise
        return {"text": plan["summary"], "plan": plan, "plans": [plan]}
