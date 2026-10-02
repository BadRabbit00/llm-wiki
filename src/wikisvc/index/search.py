import json
from typing import Any

from wikisvc.domain.errors import WikiError
from wikisvc.domain.models import Principal
from wikisvc.index.db import IndexDB
from wikisvc.index.graph import Graph, GraphStore, clearance_values
from wikisvc.index.normalize import match_query


def lifecycles(values: list[str] | None) -> list[str]:
    result = values if values is not None else ["candidate", "active"]
    if not result or set(result) - {"candidate", "active", "deprecated"}:
        raise WikiError("E_REQUEST_INVALID", "lifecycle: candidate,active,deprecated.", status=400)
    return result


class Search:
    def __init__(
        self, db: IndexDB, boosts: dict[str, float], graph: GraphStore | None = None
    ) -> None:
        self.db, self.boosts = db, boosts
        self.graph = graph or Graph(db)
        self.synonyms: list[list[str]] = []

    def search(
        self,
        query: str,
        actor: Principal,
        type_name: str | None = None,
        tag: str | None = None,
        status: str | None = None,
        sensitivity: str | None = None,
        k: int = 10,
        mode: str = "bm25",
        expand: bool = False,
        lifecycle: list[str] | None = None,
    ) -> dict[str, Any]:
        if not 1 <= k <= 50 or mode != "bm25" or len(query) > 1000:
            raise WikiError(
                "E_REQUEST_INVALID", "k: 1–50, mode: bm25, q: до 1000 символов.", status=400
            )
        allowed = lifecycles(lifecycle)
        levels = clearance_values(actor)
        hits: dict[str, dict[str, Any]] = {}
        for operator in ("AND", "OR"):
            if operator == "OR" and len(hits) >= k / 2:
                break
            match = match_query(query, self.synonyms, operator)
            if not match:
                return {"query": query, "results": []}
            with self.db.connect() as db:
                rows = db.execute(
                    f"""SELECT p.*,c.heading,c.text,bm25(chunks_fts,6.0,3.0,1.0) AS rank
                    FROM chunks_fts JOIN chunks c ON c.chunk_id=chunks_fts.rowid JOIN pages p ON p.id=c.page_id
                    WHERE chunks_fts MATCH ? AND p.sensitivity IN ({",".join("?" for _ in levels)})
                    AND (? IS NULL OR p.type=?) AND (? IS NULL OR p.status=?)
                    AND (? IS NULL OR p.sensitivity=?)
                    AND (? IS NULL OR EXISTS(SELECT 1 FROM json_each(p.tags) WHERE value=?))
                    AND (p.type!='rule' OR json_extract(p.extra,'$.lifecycle') IN ({",".join("?" for _ in allowed)}))
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
                        *allowed,
                    ),
                ).fetchall()
            for row in rows:
                if row["id"] in hits:
                    continue
                hit = {key: row[key] for key in ("id", "type", "title", "status", "summary")}
                hit.update(
                    score=-row["rank"] * self.boosts[row["status"]],
                    tier=0 if operator == "AND" else 1,
                    via="match" if operator == "AND" else "partial",
                    snippet={"heading": row["heading"], "text": row["text"][:500]},
                )
                if row["type"] == "rule":
                    extra = json.loads(row["extra"])
                    hit.update(
                        {
                            key: extra.get(key)
                            for key in ("category", "level", "lifecycle", "applies_to")
                        }
                    )
                hits[row["id"]] = hit
        matched = sorted(hits.values(), key=lambda h: (h["tier"], -h["score"], h["id"]))
        if expand:
            for root in matched[:3]:
                for node in self.graph.neighbors(root["id"], actor)["nodes"]:
                    if node["id"] in hits or node["distance"] == 0:
                        continue
                    with self.db.connect() as db:
                        row = db.execute("SELECT * FROM pages WHERE id=?", (node["id"],)).fetchone()
                    extra = json.loads(row["extra"])
                    if (
                        (type_name and row["type"] != type_name)
                        or (status and row["status"] != status)
                        or (sensitivity and row["sensitivity"] != sensitivity)
                        or (tag and tag not in json.loads(row["tags"]))
                        or (row["type"] == "rule" and extra.get("lifecycle") not in allowed)
                    ):
                        continue
                    hit = {key: node[key] for key in ("id", "type", "title", "status", "summary")}
                    hit.update(
                        score=root["score"] * 0.25,
                        tier=2,
                        via="graph",
                        snippet={"heading": "", "text": node["summary"]},
                    )
                    hits[node["id"]] = hit
        results = sorted(hits.values(), key=lambda h: (h["tier"], -h["score"], h["id"]))[:k]
        return {
            "query": query,
            "results": [
                {key: value for key, value in hit.items() if key not in ("score", "tier")}
                for hit in results
            ],
        }
