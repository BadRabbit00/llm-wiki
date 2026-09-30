import base64
import subprocess
from pathlib import Path
from typing import Any

from wikisvc.domain.errors import WikiError, not_found
from wikisvc.domain.ids import check_id
from wikisvc.domain.markdown import render
from wikisvc.domain.models import Page, Principal
from wikisvc.domain.validate import parse_page
from wikisvc.index.db import IndexDB
from wikisvc.index.graph import Graph
from wikisvc.index.indexer import row_page
from wikisvc.services.auth import can_read
from wikisvc.storage.gitrepo import GitRepo


def paginate(
    items: list[dict[str, Any]], limit: int = 50, cursor: str | None = None
) -> dict[str, Any]:
    if not 1 <= limit <= 100:
        raise WikiError("E_REQUEST_INVALID", "limit должен быть от 1 до 100.", status=400)
    offset = 0
    if cursor:
        try:
            offset = int(base64.b64decode(cursor, validate=True))
            if offset < 0:
                raise ValueError
        except (ValueError, UnicodeError) as exc:
            raise WikiError("E_CURSOR_INVALID", "Некорректный cursor.", status=400) from exc
    next_offset = offset + limit
    return {
        "items": items[offset:next_offset],
        "next_cursor": base64.b64encode(str(next_offset).encode()).decode()
        if next_offset < len(items)
        else None,
    }


class Pages:
    def __init__(self, root: Path, db: IndexDB) -> None:
        self.root, self.db = root, db

    def page(self, page_id: str, actor: Principal) -> Page:
        check_id(page_id)
        with self.db.connect() as db:
            row = db.execute("SELECT * FROM pages WHERE id=?", (page_id,)).fetchone()
        if row is None or not can_read(actor, row["sensitivity"]):
            raise not_found()
        return row_page(row)

    def list_pages(
        self,
        actor: Principal,
        type_name: str | None = None,
        status: str | None = None,
        tag: str | None = None,
        q_title: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        with self.db.connect() as db:
            rows = db.execute(
                "SELECT * FROM pages WHERE (? IS NULL OR type=?) AND (? IS NULL OR status=?) AND (? IS NULL OR EXISTS (SELECT 1 FROM json_each(pages.tags) WHERE value=?)) ORDER BY id",
                (type_name, type_name, status, status, tag, tag),
            ).fetchall()
        result = [
            {key: row[key] for key in ("id", "type", "title", "summary", "status", "updated")}
            for row in rows
            if can_read(actor, row["sensitivity"])
            and (not q_title or q_title.casefold() in row["title"].casefold())
        ]
        return paginate(result, limit, cursor)

    def get(
        self, page_id: str, actor: Principal, include: str = "", format: str = "json"
    ) -> dict[str, Any] | str:
        page = self.page(page_id, actor)
        if format == "markdown":
            return render(page.frontmatter.model_dump(mode="json"), page.body_md)
        if format != "json":
            raise WikiError("E_REQUEST_INVALID", "format: json или markdown.", status=400)
        result = self.serialize(page)
        options = set(include.split(",")) - {""}
        if options - {"backlinks", "neighbors", "history"}:
            raise WikiError(
                "E_REQUEST_INVALID", "include: backlinks,neighbors,history.", status=400
            )
        if options & {"backlinks", "neighbors"}:
            graph = Graph(self.db).neighbors(page_id, actor)
            if "neighbors" in options:
                result["neighbors"] = graph
            if "backlinks" in options:
                result["backlinks"] = [
                    {"id": e["src"], "rel": e["rel"], "kind": e["kind"]}
                    for e in graph["edges"]
                    if e["dst"] == page_id
                ]
        if "history" in options:
            result["history"] = self.history(page_id, actor)
        return result

    @staticmethod
    def serialize(page: Page) -> dict[str, Any]:
        result = page.frontmatter.model_dump(mode="json")
        result.update(
            extra=page.frontmatter.model_extra or {}, body_md=page.body_md, version=page.version
        )
        return result

    def at(self, page_id: str, commit: str, actor: Principal) -> dict[str, Any]:
        page = self.page(page_id, actor)
        repo = GitRepo(self.root)
        text = repo.show(commit, page.path)
        try:
            repo.run("merge-base", "--is-ancestor", commit, "main")
        except subprocess.CalledProcessError as exc:
            raise not_found() from exc
        historical = parse_page(text, page.path)
        if historical.id != page_id or not can_read(actor, historical.frontmatter.sensitivity):
            raise not_found()
        return self.serialize(historical)

    def history(self, page_id: str, actor: Principal) -> list[dict[str, str]]:
        page = self.page(page_id, actor)
        result = []
        for item in GitRepo(self.root).history(page.path):
            try:
                self.at(page_id, item["commit"], actor)
            except WikiError:
                continue
            result.append(item)
        return result

    def index(self, actor: Principal) -> str:
        from wikisvc.services.generators import render_index

        with self.db.connect() as db:
            pages = [
                row
                for row in db.execute("SELECT * FROM pages ORDER BY type,id")
                if can_read(actor, row["sensitivity"])
            ]
        return render_index([row_page(row) for row in pages])
