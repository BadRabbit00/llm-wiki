from typing import Any

from wikisvc.domain.errors import WikiError
from wikisvc.domain.markdown import sections
from wikisvc.domain.models import Principal
from wikisvc.index.db import IndexDB
from wikisvc.index.graph import Graph, GraphStore
from wikisvc.services.pages import Pages
from wikisvc.storage.state_db import now


class Context:
    def __init__(
        self, db: IndexDB, pages: Pages, priority: list[str], graph: GraphStore | None = None
    ) -> None:
        self.db, self.pages, self.priority = db, pages, priority
        self.graph = graph or Graph(db)

    def get(
        self,
        page_id: str,
        actor: Principal,
        depth: int = 1,
        rels: list[str] | None = None,
        budget_chars: int = 12000,
    ) -> dict[str, Any]:
        if not 1 <= depth <= 3 or not 1 <= budget_chars <= 60000:
            raise WikiError("E_REQUEST_INVALID", "depth: 1–3; budget_chars: 1–60000.", status=400)
        root = self.pages.page(page_id, actor)
        graph = self.graph.neighbors(page_id, actor, depth, rels)

        def order(node: dict[str, Any]) -> tuple[int, int, int, str]:
            rel_names = [edge["rel"] for edge in graph["edges"] if edge["dst"] == node["id"]]
            priority = min(
                (self.priority.index(rel) for rel in rel_names if rel in self.priority),
                default=len(self.priority),
            )
            return (
                node["distance"],
                priority,
                {"verified": 0, "draft": 1, "outdated": 2}[node["status"]],
                node["id"],
            )

        nodes = sorted((node for node in graph["nodes"] if node["id"] != page_id), key=order)
        candidates = [root, *(self.pages.page(node["id"], actor) for node in nodes)]
        available = sum(len(page.body_md) for page in candidates)
        delivered, pages, truncated, omitted = 0, [], [], []
        for index, page in enumerate(candidates):
            body = page.body_md
            is_truncated = index > 0 and len(body) > max(0, budget_chars - delivered)
            if is_truncated:
                truncated.append(page.id)
                body = ""
                for section in sections(page.body_md):
                    if len(body) + len(section.text) > budget_chars - delivered:
                        break
                    body += section.text
            if index > 0 and not body:
                omitted.append(page.id)
                continue
            pages.append({**Pages.serialize(page), "body_md": body, "truncated": is_truncated})
            delivered += len(body)
        with self.db.connect() as db:
            db.execute(
                "INSERT INTO delivery_stats VALUES (?,?,?,?,?,?,?)",
                (now(), "context", None, available, delivered, len(truncated), actor.clearance),
            )
        return {
            "pages": pages,
            "delivered_chars": delivered,
            "available_chars": available,
            "truncated_ids": truncated,
            "omitted_ids": omitted,
        }
