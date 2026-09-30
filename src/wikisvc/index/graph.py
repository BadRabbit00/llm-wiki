import json
from itertools import pairwise
from typing import Any

from wikisvc.domain.errors import WikiError, not_found
from wikisvc.domain.ids import check_id
from wikisvc.domain.models import Principal
from wikisvc.index.db import IndexDB


def clearance_values(principal: Principal) -> list[str]:
    levels = ["public", "internal", "restricted"]
    return levels[: levels.index(principal.clearance) + 1]


class Graph:
    def __init__(self, db: IndexDB) -> None:
        self.db = db

    def _base(
        self, actor: Principal, rels: list[str] | None, direction: str
    ) -> tuple[str, list[Any]]:
        levels = clearance_values(actor)
        parameters: list[Any] = [*levels]
        marks = ",".join("?" for _ in levels)
        relation_filter = ""
        if rels:
            relation_filter = " AND rel IN (" + ",".join("?" for _ in rels) + ")"
            parameters.extend(rels)
        select = "SELECT src,dst,rel,kind FROM visible_edges"
        reverse = "SELECT dst AS src,src AS dst,rel,kind FROM visible_edges"
        arcs = (
            select
            if direction == "out"
            else reverse
            if direction == "in"
            else select + " UNION " + reverse
        )
        sql = f"""WITH RECURSIVE visible AS (SELECT * FROM pages WHERE sensitivity IN ({marks})),
        visible_edges AS (SELECT edges.* FROM edges JOIN visible a ON a.id=edges.src JOIN visible b ON b.id=edges.dst WHERE 1=1 {relation_filter}),
        arcs AS ({arcs})"""
        return sql, parameters

    def neighbors(
        self,
        page_id: str,
        actor: Principal,
        depth: int = 1,
        rels: list[str] | None = None,
        direction: str = "both",
    ) -> dict[str, Any]:
        check_id(page_id)
        if not 1 <= depth <= 5 or direction not in ("out", "in", "both"):
            raise WikiError(
                "E_REQUEST_INVALID", "Глубина графа: 1–5; direction: out, in, both.", status=400
            )
        base, parameters = self._base(actor, rels, direction)
        with self.db.connect() as db:
            root = db.execute(
                base + " SELECT id FROM visible WHERE id=?", (*parameters, page_id)
            ).fetchone()
            if root is None:
                raise not_found()
            walk = (
                base
                + """, walk(id,distance) AS (
              SELECT ?,0 UNION SELECT arcs.dst,walk.distance+1 FROM walk JOIN arcs ON arcs.src=walk.id WHERE walk.distance<?),
              distances AS (SELECT id,MIN(distance) distance FROM walk GROUP BY id)
            """
            )
            params = (*parameters, page_id, depth)
            nodes = [
                dict(row)
                for row in db.execute(
                    walk
                    + "SELECT v.id,v.type,v.title,v.summary,v.status,d.distance FROM distances d JOIN visible v ON v.id=d.id ORDER BY d.distance,v.id",
                    params,
                )
            ]
            edges = [
                dict(row)
                for row in db.execute(
                    walk
                    + "SELECT e.* FROM visible_edges e JOIN distances a ON a.id=e.src JOIN distances b ON b.id=e.dst ORDER BY src,dst,rel,kind",
                    params,
                )
            ]
        return {"nodes": nodes, "edges": edges}

    def path(
        self, source: str, target: str, actor: Principal, max_depth: int = 5
    ) -> dict[str, Any]:
        check_id(source)
        check_id(target)
        if not 1 <= max_depth <= 5:
            raise WikiError("E_REQUEST_INVALID", "max_depth: 1–5.", status=400)
        base, parameters = self._base(actor, None, "both")
        with self.db.connect() as db:
            count = db.execute(
                base + " SELECT COUNT(*) FROM visible WHERE id IN (?,?)",
                (*parameters, source, target),
            ).fetchone()[0]
            if count != len({source, target}):
                raise not_found()
            row = db.execute(
                base
                + """, walk(id,distance,trail) AS (
                SELECT ?,0,json_array(?) UNION ALL
                SELECT a.dst,w.distance+1,json_insert(w.trail,'$[#]',a.dst) FROM walk w JOIN arcs a ON a.src=w.id
                WHERE w.distance<? AND NOT EXISTS (SELECT 1 FROM json_each(w.trail) WHERE value=a.dst)
                LIMIT 10000)
                SELECT trail FROM walk WHERE id=? ORDER BY distance LIMIT 1""",
                (*parameters, source, source, max_depth, target),
            ).fetchone()
            ids: list[str] = json.loads(row[0]) if row else []
            result_edges = []
            for left, right in pairwise(ids):
                result_edges.append(
                    dict(
                        db.execute(
                            base + " SELECT * FROM arcs WHERE src=? AND dst=? LIMIT 1",
                            (*parameters, left, right),
                        ).fetchone()
                    )
                )
        return {"nodes": ids, "edges": result_edges}

    def export(
        self, actor: Principal, type_name: str | None = None, status: str | None = None
    ) -> dict[str, Any]:
        base, parameters = self._base(actor, None, "both")
        with self.db.connect() as db:
            nodes = [
                dict(row)
                for row in db.execute(
                    base
                    + " SELECT id,type,title,summary,status FROM visible WHERE (? IS NULL OR type=?) AND (? IS NULL OR status=?) ORDER BY id",
                    (*parameters, type_name, type_name, status, status),
                )
            ]
            ids = {node["id"] for node in nodes}
            edges = [
                dict(row)
                for row in db.execute(
                    base + " SELECT * FROM visible_edges ORDER BY src,dst,rel,kind", parameters
                )
                if row["src"] in ids and row["dst"] in ids
            ]
        return {"nodes": nodes, "edges": edges}
