from __future__ import annotations

import difflib
import json
import re
import subprocess
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from wikisvc.domain.errors import WikiError, not_found
from wikisvc.domain.ids import check_id, page_path
from wikisvc.domain.markdown import edges, render, sections
from wikisvc.domain.models import Page, Principal, Proposal
from wikisvc.domain.patch import apply_patch
from wikisvc.domain.secrets import secret_kinds
from wikisvc.domain.validate import (
    check_version,
    issue,
    parse_page,
    require_valid,
    validate_page,
    validate_set,
)
from wikisvc.index.indexer import read_pages
from wikisvc.services.auth import can_read, require_human, require_role
from wikisvc.services.generators import generate
from wikisvc.services.pages import Pages, paginate
from wikisvc.storage.gitrepo import GitRepo
from wikisvc.storage.lock import write_lock
from wikisvc.storage.safefs import SafeFS
from wikisvc.storage.state_db import now

if TYPE_CHECKING:
    from wikisvc.services.runtime import Runtime


class Proposals:
    def __init__(self, runtime: Runtime) -> None:
        self.rt = runtime
        self.config = runtime.settings
        self.repo = GitRepo(self.config.wiki_root)

    def worktree(self, pid: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{32}", pid):
            raise not_found()
        return self.config.state_dir / "worktrees" / pid

    def _proposal(self, pid: str, actor: Principal, editing: bool = False) -> Proposal:
        self.worktree(pid)
        rows = self.rt.state.rows(
            "SELECT p.*,c.clearance FROM proposals p LEFT JOIN proposal_clearance c USING(pid) WHERE pid=?",
            (pid,),
        )
        if not rows or not can_read(actor, rows[0]["clearance"] or "restricted"):
            raise not_found()
        proposal = Proposal.model_validate(rows[0])
        for before, after in self._changes(proposal):
            for page in (before, after):
                if page and not can_read(actor, page.frontmatter.sensitivity):
                    raise not_found()
        if editing:
            require_role(actor, "writer")
            if proposal.author != actor.name and actor.role not in ("reviewer", "admin"):
                raise WikiError(
                    "E_FORBIDDEN", "Изменять предложение может автор или ревьюер.", status=403
                )
            if proposal.status not in ("draft", "changes_requested", "conflict"):
                raise WikiError(
                    "E_PROPOSAL_STATE", "Предложение не открыто для редактирования.", status=409
                )
        return proposal

    def _changes(self, proposal: Proposal) -> list[tuple[Page | None, Page | None]]:
        rows = self.rt.state.rows(
            "SELECT * FROM proposal_snapshots WHERE pid=? ORDER BY path", (proposal.pid,)
        )
        return [
            (
                parse_page(row["before_text"], row["path"]) if row["before_text"] else None,
                parse_page(row["after_text"], row["path"]) if row["after_text"] else None,
            )
            for row in rows
        ]

    def _snapshot(self, proposal: Proposal) -> None:
        fs = SafeFS(self.worktree(proposal.pid))
        paths = self.repo.changed(proposal.base_commit, proposal.branch)
        snapshots = []
        for path in paths:
            if (
                not path.startswith("wiki/")
                or path in ("wiki/index.md", "wiki/log.md")
                or not path.endswith(".md")
            ):
                raise WikiError("E_PROPOSAL_PATH", "Предложение может менять только страницы вики.")
            try:
                before: str | None = self.repo.show(proposal.base_commit, path)
            except WikiError as exc:
                if exc.status != 404:
                    raise
                before = None
            after = fs.read(path) if fs.path(path).exists() else None
            snapshots.append((proposal.pid, path, before, after))
        with self.rt.state.connect() as db:
            db.execute("DELETE FROM proposal_snapshots WHERE pid=?", (proposal.pid,))
            db.executemany("INSERT INTO proposal_snapshots VALUES (?,?,?,?)", snapshots)

    def _status(
        self, proposal: Proposal, status: str, actor: Principal, comment: str | None = None
    ) -> None:
        with self.rt.state.connect() as db:
            db.execute(
                "UPDATE proposals SET status=?,updated_at=?,review_comment=?,decided_by=? WHERE pid=?",
                (
                    status,
                    now(),
                    comment,
                    actor.name if status in ("accepted", "rejected", "changes_requested") else None,
                    proposal.pid,
                ),
            )
            if status in ("accepted", "rejected"):
                db.execute(
                    "UPDATE findings SET status=?,reason=?,updated_at=? WHERE proposal_pid=?",
                    (
                        "resolved" if status == "accepted" else "dismissed",
                        comment,
                        now(),
                        proposal.pid,
                    ),
                )
        self.rt.state.audit(actor.name, "proposal." + status, proposal.pid)

    def create(
        self, actor: Principal, title: str, description: str = "", kind: str = "manual"
    ) -> dict[str, Any]:
        require_role(actor, "writer")
        if kind not in ("manual", "chat", "book", "heal"):
            raise WikiError("E_REQUEST_INVALID", "kind: manual, chat, book, heal.", status=400)
        if not 3 <= len(title) <= 200 or len(description) > 12000 or "\n" in title:
            raise WikiError(
                "E_REQUEST_INVALID",
                "title: 3–200 символов одной строкой; description: до 12000.",
                status=400,
            )
        if secret_kinds(title + "\n" + description, self.config.secret_entropy_threshold):
            raise WikiError("E_SECRET_DETECTED", "В описании предложения найден возможный секрет.")
        with write_lock(self.config.state_dir, self.config.lock_timeout):
            self.repo.ensure_main()
            self.expire()
            pid = uuid.uuid4().hex
            proposal = Proposal(
                pid=pid,
                title=title,
                description=description,
                author=actor.name,
                kind=kind,  # type: ignore[arg-type]
                author_identity=actor.identity,
                author_kind=actor.kind,
                status="draft",
                base_commit=self.repo.head(),
                branch="proposal/" + pid,
                created_at=now(),
                updated_at=now(),
            )
            self.repo.add_worktree(self.worktree(pid), proposal.branch)
            try:
                with self.rt.state.connect() as db:
                    db.execute(
                        "INSERT INTO proposals (pid,title,description,author,status,base_commit,branch,review_comment,created_at,updated_at,decided_by,last_editor,kind,author_identity,author_kind) VALUES (:pid,:title,:description,:author,:status,"
                        ":base_commit,:branch,:review_comment,:created_at,:updated_at,:decided_by,:last_editor,:kind,:author_identity,:author_kind)",
                        proposal.model_dump(),
                    )
                    db.execute(
                        "INSERT INTO proposal_clearance VALUES (?,?)", (pid, actor.clearance)
                    )
            except Exception:
                self.repo.remove_worktree(self.worktree(pid), proposal.branch)
                raise
            self.rt.state.audit(actor.name, "proposal.create", pid)
        return proposal.model_dump()

    def get(self, pid: str, actor: Principal) -> dict[str, Any]:
        proposal = self._proposal(pid, actor)
        validation = self.rt.state.rows(
            "SELECT result FROM proposal_validation WHERE pid=?", (pid,)
        )
        return {
            **proposal.model_dump(),
            "pages": [
                Pages.serialize(page)
                for before, after in self._changes(proposal)
                if (page := after or before) is not None
            ],
            "validation": json.loads(validation[0]["result"]) if validation else None,
            "notes": self.notes(pid),
        }

    def notes(self, pid: str) -> dict[str, Any] | None:
        rows = self.rt.state.rows("SELECT data FROM proposal_notes WHERE pid=?", (pid,))
        return json.loads(rows[0]["data"]) if rows else None

    def put_notes(self, pid: str, actor: Principal, notes: dict[str, Any]) -> dict[str, Any]:
        with write_lock(self.config.state_dir, self.config.lock_timeout):
            proposal = self._proposal(pid, actor, editing=True)
            if proposal.author != actor.name:
                raise WikiError("E_FORBIDDEN", "Заметки может менять только автор.", status=403)
            data = json.dumps(notes, ensure_ascii=False)
            if len(data) > 100000:
                raise WikiError("E_REQUEST_INVALID", "Заметки слишком велики.", status=400)
            if secret_kinds(data, self.config.secret_entropy_threshold):
                raise WikiError("E_SECRET_DETECTED", "В заметках найден возможный секрет.")
            with self.rt.state.connect() as db:
                db.execute("INSERT OR REPLACE INTO proposal_notes VALUES (?,?)", (pid, data))
        return notes

    def list_proposals(
        self,
        actor: Principal,
        status: str | None = None,
        author: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
        kind: str | None = None,
    ) -> dict[str, Any]:
        result = []
        for row in self.rt.state.rows(
            "SELECT pid FROM proposals WHERE (? IS NULL OR status=?) AND (? IS NULL OR author=?) AND (? IS NULL OR kind=?) ORDER BY created_at,pid",
            (status, status, author, author, kind, kind),
        ):
            try:
                result.append(self._proposal(row["pid"], actor).model_dump())
            except WikiError as exc:
                if exc.status != 404:
                    raise
        return paginate(result, limit, cursor)

    def _overlay(self, proposal: Proposal) -> list[Page]:
        pages = {page.id: page for page in self.rt.indexer.pages()}
        for before, after in self._changes(proposal):
            if before:
                pages.pop(before.id, None)
            if after:
                pages[after.id] = after
        return list(pages.values())

    def _sync_main(self) -> None:
        self.repo.ensure_main()
        self.rt.sync_index()

    def _existing(self, proposal: Proposal, page_id: str) -> Page | None:
        for before, after in self._changes(proposal):
            if (before and before.id == page_id) or (after and after.id == page_id):
                return after
        # Resolve only the requested file in the proposal's base, including app-doc paths.
        slug = page_id.split("-", 1)[1]
        fs = SafeFS(self.worktree(proposal.pid))
        for path in GitRepo(self.worktree(proposal.pid)).run("ls-files", "--", "wiki").splitlines():
            if path.endswith(f"/{slug}.md") or path == f"wiki/apps/{slug}/index.md":
                page = parse_page(fs.read(path), path)
                if page.id == page_id:
                    return page
        return None

    def _edited(self, proposal: Proposal, actor: Principal) -> None:
        with self.rt.state.connect() as db:
            db.execute("UPDATE proposals SET last_editor=? WHERE pid=?", (actor.name, proposal.pid))
            db.execute(
                "INSERT OR IGNORE INTO proposal_editors(pid,name,identity) VALUES (?,?,?)",
                (proposal.pid, actor.name, actor.identity),
            )
            db.execute("DELETE FROM proposal_validation WHERE pid=?", (proposal.pid,))

    def _downgrades(self, proposal: Proposal) -> list[dict[str, Any]]:
        levels = ["public", "internal", "restricted"]
        return [
            issue(
                "W_SENSITIVITY_DOWNGRADE",
                after.id,
                f"Чувствительность понижена: {before.frontmatter.sensitivity} → {after.frontmatter.sensitivity}.",
                "Ревьюер должен явно проверить допустимость раскрытия информации.",
            ).model_dump()
            for before, after in self._changes(proposal)
            if before
            and after
            and levels.index(after.frontmatter.sensitivity)
            < levels.index(before.frontmatter.sensitivity)
        ]

    def _source(self, page: Page) -> None:
        if page.frontmatter.type != "source":
            return
        extra = page.frontmatter.model_extra or {}
        path = extra.get("raw_path", "")
        if not isinstance(path, str) or not path.startswith(("raw/", "library/")):
            raise WikiError("E_PATH_UNSAFE", "raw_path должен находиться в raw/ или library/.")
        from wikisvc.storage.raw_paths import raw_path

        file = raw_path(self.config.wiki_root, self.config.state_dir, path)
        with self.rt.index.connect() as db:
            row = db.execute("SELECT sha256 FROM raw_files WHERE path=?", (path,)).fetchone()
        if not file.is_file() or not row or row[0] != extra.get("raw_sha256"):
            raise WikiError("E_SOURCE_HASH", "Источник отсутствует или raw_sha256 не совпадает.")

    def _put(
        self,
        proposal: Proposal,
        page_id: str,
        actor: Principal,
        metadata: dict[str, Any],
        body: str,
        base_version: str | None,
    ) -> dict[str, Any]:
        check_id(page_id)
        if metadata.get("id") != page_id:
            raise WikiError("E_ID_INVALID", "ID в URL и frontmatter должны совпадать.")
        existing = self._existing(proposal, page_id)
        with self.rt.index.connect() as db:
            current = db.execute(
                "SELECT content_hash,sensitivity FROM pages WHERE id=?", (page_id,)
            ).fetchone()
        if (current and not can_read(actor, current["sensitivity"])) or (
            existing and not can_read(actor, existing.frontmatter.sensitivity)
        ):
            raise not_found()
        check_version(base_version, current["content_hash"] if current else None)
        metadata = dict(metadata)
        metadata.update(
            status="draft",
            created=existing.frontmatter.created if existing else now(),
            updated=now(),
            verified_by=None,
            verified_at=None,
        )
        metadata.setdefault("sensitivity", "internal")
        if metadata.get("type") == "rule":
            protected = (
                "lifecycle",
                "level",
                "priority",
                "owner",
                "deprecated_reason",
                "verified_by",
                "verified_at",
            )
            saved = existing.frontmatter.model_dump() if existing else {}
            for field in protected:
                metadata.pop(field, None)
                if existing and field in saved:
                    metadata[field] = saved[field]
            if existing is None:
                metadata.update(
                    lifecycle="candidate",
                    level="should",
                    priority=3,
                    verified_by=None,
                    verified_at=None,
                )
        page = parse_page(render(metadata, body))
        if not can_read(actor, page.frontmatter.sensitivity):
            raise not_found()
        if existing and existing.frontmatter.type != page.frontmatter.type:
            raise WikiError("E_TYPE_UNKNOWN", "Тип существующей страницы менять нельзя.")
        page.path = page_path(
            self.rt.registry,
            page.frontmatter.type,
            page_id,
            (page.frontmatter.model_extra or {}).get("parent"),
        )
        require_valid(validate_page(page, self.rt.registry, self.config.secret_entropy_threshold))
        overlay = {item.id: item for item in self._overlay(proposal)}
        for edge in edges(page):
            if edge.dst in overlay and not can_read(
                actor, overlay[edge.dst].frontmatter.sensitivity
            ):
                raise not_found()
        self._source(page)
        overlay[page.id] = page
        require_valid(self.rt.extractions.citation_issues(list(overlay.values()), {page.id}))
        fs = SafeFS(self.worktree(proposal.pid))
        if fs.path(page.path).exists() and parse_page(fs.read(page.path)).id != page.id:
            raise WikiError("E_ID_DUPLICATE", "Путь занят другой страницей.")
        text = render(page.frontmatter.model_dump(mode="json"), page.body_md)
        repo = GitRepo(self.worktree(proposal.pid))
        paths = list({page.path, existing.path if existing else page.path})
        with repo.transaction(paths):
            fs.write(page.path, text)
            if existing and existing.path != page.path:
                fs.remove(existing.path)
            repo.commit(f"Update {page_id}", actor.name, paths)
        self._snapshot(proposal)
        self._edited(proposal, actor)
        self._status(proposal, "draft", actor)
        self.rt.state.audit(actor.name, "page.put", page_id)
        return Pages.serialize(parse_page(text, page.path))

    def put(
        self,
        pid: str,
        page_id: str,
        actor: Principal,
        metadata: dict[str, Any],
        body: str,
        base_version: str | None = None,
    ) -> dict[str, Any]:
        with write_lock(self.config.state_dir, self.config.lock_timeout):
            self._sync_main()
            return self._put(
                self._proposal(pid, actor, editing=True),
                page_id,
                actor,
                metadata,
                body,
                base_version,
            )

    def patch(
        self,
        pid: str,
        page_id: str,
        actor: Principal,
        ops: list[dict[str, Any]],
        base_version: str | None = None,
    ) -> dict[str, Any]:
        check_id(page_id)
        with write_lock(self.config.state_dir, self.config.lock_timeout):
            self._sync_main()
            proposal = self._proposal(pid, actor, editing=True)
            page = self._existing(proposal, page_id)
            if not page or not can_read(actor, page.frontmatter.sensitivity):
                raise not_found()
            metadata, body = apply_patch(
                page.frontmatter.model_dump(mode="json"), page.body_md, ops
            )
            return self._put(proposal, page_id, actor, metadata, body, base_version)

    def delete(
        self, pid: str, page_id: str, actor: Principal, base_version: str | None = None
    ) -> dict[str, str]:
        check_id(page_id)
        with write_lock(self.config.state_dir, self.config.lock_timeout):
            self._sync_main()
            proposal = self._proposal(pid, actor, editing=True)
            pages = self._overlay(proposal)
            page = next((page for page in pages if page.id == page_id), None)
            if not page or not can_read(actor, page.frontmatter.sensitivity):
                raise not_found()
            if any(
                edge.dst == page_id and edge.src != page_id
                for item in pages
                for edge in edges(item)
            ) or any(
                (item.frontmatter.model_extra or {}).get("parent") == page_id
                or (item.frontmatter.model_extra or {}).get("owner") == page_id
                for item in pages
                if item.id != page_id
            ):
                raise WikiError(
                    "E_LINK_UNRESOLVED",
                    "На страницу остались входящие ссылки.",
                    "Сначала уберите ссылки в этом предложении.",
                )
            if base_version is not None:
                check_version(base_version, self.rt.pages.page(page_id, actor).version)
            fs = SafeFS(self.worktree(pid))
            if not fs.path(page.path).exists():
                raise not_found()
            repo = GitRepo(self.worktree(pid))
            with repo.transaction([page.path]):
                fs.remove(page.path)
                repo.commit(f"Delete {page_id}", actor.name, [page.path])
            self._snapshot(proposal)
            self._edited(proposal, actor)
            self._status(proposal, "draft", actor)
            self.rt.state.audit(actor.name, "page.delete", page_id)
        return {"id": page_id, "change": "deleted"}

    def _validation(self, proposal: Proposal) -> dict[str, Any]:
        baseline = {
            (i.code, i.page, i.message)
            for i in validate_set(
                self.rt.indexer.pages(), self.rt.registry, self.rt.indexer.validation
            )
            if i.severity == "error"
        }
        changed = {page.id for pair in self._changes(proposal) for page in pair if page}
        issues = validate_set(self._overlay(proposal), self.rt.registry, self.rt.indexer.validation)
        errors = [
            i
            for i in issues
            if i.severity == "error"
            and (i.page in changed or (i.code, i.page, i.message) not in baseline)
        ]
        citation_problems = self.rt.extractions.citation_issues(self._overlay(proposal))
        errors.extend(i for i in citation_problems if i.severity == "error" and i.page in changed)
        issues.extend(citation_problems)
        warnings = [i for i in issues if i.severity != "error" and i.page in changed]
        for _, page in self._changes(proposal):
            if page:
                self._source(page)
        result = {
            "errors": [i.model_dump() for i in errors],
            "warnings": [i.model_dump() for i in warnings] + self._downgrades(proposal),
        }
        with self.rt.state.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO proposal_validation VALUES (?,?)",
                (proposal.pid, json.dumps(result, ensure_ascii=False)),
            )
        return result

    def validate(self, pid: str, actor: Principal) -> dict[str, Any]:
        require_role(actor, "writer")
        with write_lock(self.config.state_dir, self.config.lock_timeout):
            self._sync_main()
            proposal = self._proposal(pid, actor)
            return self._validation(proposal)

    def submit(self, pid: str, actor: Principal) -> dict[str, Any]:
        with write_lock(self.config.state_dir, self.config.lock_timeout):
            self._sync_main()
            proposal = self._proposal(pid, actor, editing=True)
            self._snapshot(proposal)
            if not self._changes(proposal):
                raise WikiError("E_PROPOSAL_EMPTY", "В предложении нет изменений.")
            validation = self._validation(proposal)
            if validation["errors"]:
                raise WikiError(
                    validation["errors"][0]["code"],
                    "Предложение не прошло валидацию.",
                    details=validation["errors"],
                )
            self._status(proposal, "submitted", actor)
        return self.get(pid, actor)

    def diff(self, pid: str, actor: Principal) -> dict[str, Any]:
        proposal = self._proposal(pid, actor)
        downgrades = self._downgrades(proposal)
        result, added, removed = [], set(), set()
        for before, after in self._changes(proposal):
            page = after or before
            assert page is not None
            old = before.frontmatter.model_dump(mode="json") if before else {}
            new = after.frontmatter.model_dump(mode="json") if after else {}
            fields = [
                {"field": key, "before": old.get(key), "after": new.get(key)}
                for key in sorted(old.keys() | new.keys())
                if old.get(key) != new.get(key)
            ]
            old_sections = {s.heading: s.text for s in sections(before.body_md)} if before else {}
            new_sections = {s.heading: s.text for s in sections(after.body_md)} if after else {}
            diffs = [
                {
                    "heading": key,
                    "change": "added"
                    if key not in old_sections
                    else "deleted"
                    if key not in new_sections
                    else "modified",
                    "unified_diff": "".join(
                        difflib.unified_diff(
                            old_sections.get(key, "").splitlines(keepends=True),
                            new_sections.get(key, "").splitlines(keepends=True),
                            fromfile="before",
                            tofile="after",
                        )
                    ),
                }
                for key in sorted(old_sections.keys() | new_sections.keys())
                if old_sections.get(key) != new_sections.get(key)
            ]
            result.append(
                {
                    "id": page.id,
                    "change": "added" if not before else "deleted" if not after else "modified",
                    "frontmatter_diff": fields,
                    "sections": diffs,
                    "warnings": [w for w in downgrades if w["page"] == page.id],
                }
            )
            previous = set(edges(before)) if before else set()
            current = set(edges(after)) if after else set()
            added.update(current - previous)
            removed.update(previous - current)
        validation = self.rt.state.rows(
            "SELECT result FROM proposal_validation WHERE pid=?", (pid,)
        )
        return {
            "pid": pid,
            "base_commit": proposal.base_commit,
            "pages": result,
            "edges_added": [
                e.model_dump() for e in sorted(added, key=lambda e: (e.src, e.dst, e.rel, e.kind))
            ],
            "edges_removed": [
                e.model_dump() for e in sorted(removed, key=lambda e: (e.src, e.dst, e.rel, e.kind))
            ],
            "validation": json.loads(validation[0]["result"])
            if validation
            else {"errors": [], "warnings": []},
        }

    def decide(
        self,
        pid: str,
        actor: Principal,
        decision: str,
        comment: str = "",
        promote: list[dict[str, Any]] | None = None,
        deprecate: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        if decision not in {"accepted", "rejected", "changes_requested", "abandoned"}:
            raise WikiError("E_PROPOSAL_STATE", "Неизвестное решение.", status=400)
        require_role(actor, "writer" if decision == "abandoned" else "reviewer")
        if decision != "abandoned":
            require_human(actor)
        if len(comment) > 12000:
            raise WikiError("E_REQUEST_INVALID", "Недопустимый комментарий.")
        if secret_kinds(comment, self.config.secret_entropy_threshold):
            raise WikiError("E_SECRET_DETECTED", "В комментарии найден возможный секрет.")
        with write_lock(self.config.state_dir, self.config.lock_timeout):
            proposal = self._proposal(pid, actor)
            if decision == "abandoned" and proposal.author != actor.name:
                require_role(actor, "reviewer")
            if proposal.status in ("accepted", "rejected", "abandoned", "reverted") or (
                decision in ("accepted", "changes_requested")
                and proposal.status != "submitted"
                and not (
                    decision == "accepted"
                    and proposal.status == "draft"
                    and proposal.author_kind == "agent"
                )
            ):
                raise WikiError("E_PROPOSAL_STATE", "Переход состояния недопустим.", status=409)
            if decision == "accepted":
                editors = self.rt.state.rows(
                    "SELECT name,identity FROM proposal_editors WHERE pid=?", (pid,)
                )
                if actor.identity in {
                    proposal.author_identity or proposal.author,
                    *(row["identity"] or row["name"] for row in editors),
                }:
                    self.rt.state.audit(
                        actor.name, "proposal.accept", pid, ok=False, detail="self-review"
                    )
                    raise WikiError(
                        "E_SELF_REVIEW",
                        "Автор и редакторы не могут принять это предложение.",
                        status=403,
                    )
                self._sync_main()
                self._snapshot(proposal)
                if not self._changes(proposal):
                    raise WikiError("E_PROPOSAL_EMPTY", "В предложении нет изменений.")
                validation = self._validation(proposal)
                if validation["errors"]:
                    raise WikiError(
                        "E_VALIDATION",
                        "Перед принятием обнаружены ошибки.",
                        details=validation["errors"],
                    )
                base = self.repo.head()
                prior_pages, prior_parse_errors = (
                    self.rt.indexer.pages(),
                    self.rt.indexer.failures(),
                )
                prior_errors = {
                    (i.code, i.page, i.message)
                    for i in validate_set(prior_pages, self.rt.registry, self.rt.indexer.validation)
                    + prior_parse_errors
                    if i.severity == "error"
                }
                paths = self.repo.changed(proposal.base_commit, proposal.branch)
                targets = {
                    p.id for _, p in self._changes(proposal) if p and p.frontmatter.type == "rule"
                }
                requests = [("promote", item) for item in (promote or [])] + [
                    ("deprecate", item) for item in (deprecate or [])
                ]
                target_ids = [item.get("id") for _, item in requests]
                if any(target not in targets for target in target_ids) or len(
                    set(target_ids)
                ) != len(target_ids):
                    raise WikiError(
                        "E_RULE_NOT_IN_PROPOSAL",
                        "Правило должно входить в предложение; решения не должны повторяться.",
                    )
                with self.repo.transaction([*paths, "wiki/index.md", "wiki/log.md"]):
                    try:
                        self.repo.run(
                            "merge", "--no-ff", "--no-commit", proposal.branch, author=actor.name
                        )
                    except subprocess.CalledProcessError as exc:
                        raise WikiError(
                            "E_MERGE_CONFLICT",
                            "Конфликт слияния; main не изменён.",
                            "Исправьте конфликт в предложении или создайте новое на актуальном main.",
                            status=409,
                        ) from exc
                    changed, parse_errors = read_pages(self.config.wiki_root, paths)
                    from wikisvc.services.review import rule_decision

                    fs = SafeFS(self.config.wiki_root)
                    for index, page in enumerate(changed):
                        if (
                            page.frontmatter.type == "rule"
                            and (page.frontmatter.model_extra or {}).get("lifecycle") == "active"
                        ):
                            metadata = page.frontmatter.model_dump(mode="json")
                            metadata.update(
                                status="verified", verified_by=actor.identity, verified_at=now()
                            )
                            changed[index] = parse_page(render(metadata, page.body_md), page.path)
                    for operation, values in requests:
                        index = next(i for i, p in enumerate(changed) if p.id == values["id"])
                        changed[index] = rule_decision(
                            changed[index],
                            actor,
                            operation,
                            {k: v for k, v in values.items() if k != "id"},
                        )
                    for page in changed:
                        fs.write(
                            page.path,
                            render(page.frontmatter.model_dump(mode="json"), page.body_md),
                        )
                    merged = [p for p in prior_pages if p.path not in paths] + changed
                    merged_errors = [
                        problem
                        for problem in validate_set(
                            merged, self.rt.registry, self.rt.indexer.validation
                        )
                        + parse_errors
                        if problem.severity == "error"
                        and (problem.code, problem.page, problem.message) not in prior_errors
                    ]
                    require_valid(merged_errors)
                    require_valid(
                        [
                            i
                            for i in self.rt.extractions.citation_issues(merged)
                            if i.page in targets
                        ]
                    )
                    generate(
                        self.config.wiki_root,
                        f"Принято {pid}: {proposal.title}",
                        actor.name,
                        merged,
                    )
                    self.repo.commit(
                        f"Accept proposal {pid}",
                        actor.name,
                        [*paths, "wiki/index.md", "wiki/log.md"],
                    )
                with self.rt.state.connect() as db:
                    db.execute(
                        "UPDATE proposals SET accepted_commit=? WHERE pid=?",
                        (self.repo.head(), pid),
                    )
                self.rt.state.audit(
                    actor.name,
                    "proposal.rule-decisions",
                    pid,
                    detail=json.dumps({"promote": promote or [], "deprecate": deprecate or []}),
                )
                self._status(proposal, decision, actor, comment)
                self.rt.indexer.reindex(self.repo.changed(base))
                self.repo.remove_worktree(self.worktree(pid), proposal.branch)
            else:
                if (
                    decision == "rejected"
                    and self.rt.state.rows("SELECT id FROM findings WHERE proposal_pid=?", (pid,))
                    and not comment.strip()
                ):
                    raise WikiError(
                        "E_REQUEST_INVALID", "Для отклонения находки нужна причина.", status=400
                    )
                self._status(proposal, decision, actor, comment)
                if decision in ("rejected", "abandoned"):
                    self.repo.remove_worktree(self.worktree(pid), proposal.branch)
        return self.get(pid, actor)

    def revert(self, pid: str, actor: Principal) -> dict[str, Any]:
        require_human(actor)
        with write_lock(self.config.state_dir, self.config.lock_timeout):
            proposal = self._proposal(pid, actor)
            if proposal.status != "accepted" or not proposal.accepted_commit:
                raise WikiError(
                    "E_PROPOSAL_STATE", "Откат доступен только принятому предложению.", status=409
                )
            self._sync_main()
            commit = proposal.accepted_commit
            paths = [p.path for pair in self._changes(proposal) for p in pair if p]
            later = set(
                self.repo.run(
                    "log", "--format=", "--name-only", commit + "..HEAD", "--", *sorted(set(paths))
                ).splitlines()
            )
            overlap = sorted(set(paths) & later)
            if overlap:
                raise WikiError(
                    "E_REVERT_CONFLICT",
                    "Позднейшие коммиты затрагивают те же страницы.",
                    details=[{"path": p} for p in overlap],
                    status=409,
                )
            generated = ["wiki/index.md", "wiki/log.md"]
            base = self.repo.head()
            prior = self.rt.indexer.pages()
            baseline = {
                (i.code, i.page, i.message)
                for i in validate_set(prior, self.rt.registry)
                if i.severity == "error"
            }
            with self.repo.transaction([*paths, *generated]):
                try:
                    self.repo.run("revert", "-m", "1", "--no-commit", commit, author=actor.name)
                except subprocess.CalledProcessError as exc:
                    unresolved = set(
                        self.repo.run("diff", "--name-only", "--diff-filter=U").splitlines()
                    )
                    if not unresolved or unresolved - set(generated):
                        raise WikiError(
                            "E_REVERT_CONFLICT",
                            "Не удалось откатить страницы.",
                            details=[{"path": p} for p in sorted(unresolved)],
                            status=409,
                        ) from exc
                # Generated views are rebuilt from the reverted content, retaining the audit log.
                self.repo.run(
                    "restore", "--source", base, "--staged", "--worktree", "--", *generated
                )
                if (
                    self.repo.git_path("REVERT_HEAD").exists()
                    or self.repo.git_path("sequencer").exists()
                ):
                    self.repo.run("revert", "--quit")
                changed, errors = read_pages(self.config.wiki_root, sorted(set(paths)))
                merged = [p for p in prior if p.path not in paths] + changed
                issues = validate_set(merged, self.rt.registry) + errors
                require_valid([i for i in issues if (i.code, i.page, i.message) not in baseline])
                generate(
                    self.config.wiki_root,
                    f"Отменено {pid}: {proposal.title}",
                    actor.identity,
                    merged,
                )
                reverted = self.repo.commit(
                    "Revert proposal " + pid, actor.name, [*paths, *generated]
                )
            with self.rt.state.connect() as db:
                db.execute("UPDATE proposals SET reverted_commit=? WHERE pid=?", (reverted, pid))
                db.execute(
                    "UPDATE findings SET status='open',updated_at=? WHERE proposal_pid=? AND status='resolved'",
                    (now(), pid),
                )
            self._status(proposal, "reverted", actor)
            self.rt.indexer.reindex(self.repo.changed(base))
        return self.get(pid, actor)

    def recover(self) -> None:
        """Reconcile a durable merge if the process stopped before updating state.db."""
        branches = set(
            self.repo.run(
                "for-each-ref", "--format=%(refname:short)", "refs/heads/proposal/"
            ).splitlines()
        )
        for row in self.rt.state.rows("SELECT * FROM proposals"):
            proposal = Proposal.model_validate(row)
            work = self.worktree(proposal.pid)
            if proposal.status == "accepted":
                reverted = self.repo.run(
                    "log",
                    "-1",
                    "--format=%H",
                    "--grep",
                    f"^Revert proposal {proposal.pid}$",
                    "main",
                )
                if reverted:
                    with self.rt.state.connect() as db:
                        db.execute(
                            "UPDATE proposals SET status='reverted',reverted_commit=? WHERE pid=?",
                            (reverted, proposal.pid),
                        )
                        db.execute(
                            "UPDATE findings SET status='open' WHERE proposal_pid=? AND status='resolved'",
                            (proposal.pid,),
                        )
            if proposal.status in ("accepted", "rejected", "abandoned", "reverted"):
                if work.exists() or proposal.branch in branches:
                    self.repo.remove_worktree(work, proposal.branch)
                continue
            if not work.exists():
                continue
            branch = GitRepo(work)
            branch.recover()
            self._snapshot(proposal)
            authors = branch.run(
                "log", "--format=%an", proposal.base_commit + "..HEAD"
            ).splitlines()
            with self.rt.state.connect() as db:
                db.executemany(
                    "INSERT OR IGNORE INTO proposal_editors(pid,name,identity) VALUES (?,?,COALESCE((SELECT person FROM tokens WHERE name=?),?))",
                    [(proposal.pid, name, name, name) for name in set(authors)],
                )
                if authors:
                    db.execute(
                        "UPDATE proposals SET last_editor=? WHERE pid=?", (authors[0], proposal.pid)
                    )
            if (
                proposal.status not in ("draft", "submitted")
                or branch.head() == proposal.base_commit
            ):
                continue
            try:
                self.repo.run("merge-base", "--is-ancestor", proposal.branch, "main")
            except subprocess.CalledProcessError:
                continue
            name = self.repo.run(
                "log",
                "-1",
                "--format=%an",
                "--merges",
                "--grep",
                f"^Accept proposal {proposal.pid}$",
                "main",
            )
            if not name:
                continue
            actor = Principal(name=name, role="admin", clearance="restricted")
            commit = self.repo.run(
                "log",
                "-1",
                "--format=%H",
                "--merges",
                "--grep",
                f"^Accept proposal {proposal.pid}$",
                "main",
            )
            with self.rt.state.connect() as db:
                db.execute(
                    "UPDATE proposals SET accepted_commit=? WHERE pid=?", (commit, proposal.pid)
                )
            self._status(proposal, "accepted", actor, "Recovered after committed merge")
            self.repo.remove_worktree(work, proposal.branch)

    def expire(self) -> None:
        deadline = (datetime.now(UTC) - timedelta(days=self.config.proposal_ttl_days)).isoformat()
        actor = Principal(name="service", role="admin", clearance="restricted")
        for row in self.rt.state.rows(
            "SELECT * FROM proposals WHERE status IN ('draft','submitted','changes_requested','conflict') AND updated_at<?",
            (deadline,),
        ):
            proposal = Proposal.model_validate(row)
            self._status(proposal, "abandoned", actor, "TTL expired")
            self.repo.remove_worktree(self.worktree(proposal.pid), proposal.branch)
