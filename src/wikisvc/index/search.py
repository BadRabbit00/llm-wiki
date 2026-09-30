from typing import Any

from wikisvc.domain.errors import WikiError
from wikisvc.domain.models import Principal
from wikisvc.index.db import IndexDB
from wikisvc.index.graph import Graph, clearance_values
from wikisvc.index.normalize import match_query


class Search:
    def __init__(self, db: IndexDB, boosts: dict[str, float]) -> None:
        self.db, self.boosts = db, boosts

    def search(
        self,
        query: str,
        actor: Principal,
        type_name: str | None = None,
        tag: str | None = None,
        status: str | None = None,
        sensitivity: str | None = None,
        k: int = 10,
        mode: str = "hybrid",
        expand: bool = False,
    ) -> dict[str, Any]:
        if not 1 <= k <= 50 or mode not in ("hybrid", "bm25", "vector") or len(query) > 1000:
            raise WikiError(
                "E_REQUEST_INVALID",
                "k: 1–50, mode: hybrid/bm25/vector, q: до 1000 символов.",
                status=400,
            )
        # No external provider is configured in the deterministic MVP.
        if mode == "vector":
            raise WikiError(
                "E_EMBEDDINGS_UNAVAILABLE",
                "Провайдер эмбеддингов не настроен.",
                "Используйте mode=bm25 или hybrid.",
                status=400,
            )
        match = match_query(query)
        if not match:
            return {"query": query, "results": []}
        levels = clearance_values(actor)
        marks = ",".join("?" for _ in levels)
        with self.db.connect() as db:
            rows = db.execute(
                f"""SELECT p.*, c.heading, c.text, bm25(chunks_fts,6.0,3.0,1.0) AS rank
                FROM chunks_fts JOIN chunks c ON c.chunk_id=chunks_fts.rowid JOIN pages p ON p.id=c.page_id
                WHERE chunks_fts MATCH ? AND p.sensitivity IN ({marks})
                AND (? IS NULL OR p.type=?) AND (? IS NULL OR p.status=?)
                AND (? IS NULL OR p.sensitivity=?)
                AND (? IS NULL OR EXISTS (SELECT 1 FROM json_each(p.tags) WHERE value=?))
                ORDER BY rank,p.id LIMIT 50""",
                (
                    match,
                    *levels,
                    type_name,
                    type_name,
                    status,
                    status,
                    sensitivity,
                    sensitivity,
                    tag,
                    tag,
                ),
            ).fetchall()
        hits: dict[str, dict[str, Any]] = {}
        for row in rows:
            if row["id"] not in hits:
                hits[row["id"]] = {
                    key: row[key] for key in ("id", "type", "title", "status", "summary")
                }
                hits[row["id"]].update(
                    score=-row["rank"] * self.boosts[row["status"]],
                    via="match",
                    snippet={"heading": row["heading"], "text": row["text"][:500]},
                )
        matched = sorted(hits.values(), key=lambda hit: (-hit["score"], hit["id"]))
        if expand:
            for root in matched[:3]:
                for node in Graph(self.db).neighbors(root["id"], actor)["nodes"]:
                    if node["id"] in hits or node["distance"] == 0:
                        continue
                    with self.db.connect() as db:
                        row = db.execute("SELECT * FROM pages WHERE id=?", (node["id"],)).fetchone()
                    import json

                    if (
                        (type_name and row["type"] != type_name)
                        or (status and row["status"] != status)
                        or (sensitivity and row["sensitivity"] != sensitivity)
                        or (tag and tag not in json.loads(row["tags"]))
                    ):
                        continue
                    hits[node["id"]] = {
                        key: node[key] for key in ("id", "type", "title", "status", "summary")
                    }
                    hits[node["id"]].update(
                        score=root["score"] * 0.25,
                        via="graph",
                        snippet={"heading": "", "text": node["summary"]},
                    )
        return {
            "query": query,
            "results": sorted(hits.values(), key=lambda hit: (-hit["score"], hit["id"]))[:k],
        }
