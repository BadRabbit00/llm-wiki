import json
import sqlite3
from typing import Any, Protocol

from wikisvc.domain.errors import WikiError, not_found
from wikisvc.domain.ids import check_id
from wikisvc.domain.models import Principal
from wikisvc.index.db import IndexDB


def clearance_values(principal: Principal) -> list[str]:
    levels = ["public", "internal", "restricted"]
    return levels[: levels.index(principal.clearance) + 1]


class GraphStore(Protocol):
    def neighbors(
        self,
        page_id: str,
        actor: Principal,
        depth: int = 1,
        rels: list[str] | None = None,
        direction: str = "both",
    ) -> dict[str, Any]: ...
    def path(
        self, source: str, target: str, actor: Principal, max_depth: int = 5
    ) -> dict[str, Any]: ...
    def impact(
        self, page_id: str, actor: Principal, depth: int = 2, rels: list[str] | None = None
    ) -> dict[str, Any]: ...
    def subgraph(
        self, ids: list[str], actor: Principal, rels: list[str] | None = None, depth: int = 1
    ) -> dict[str, Any]: ...
    def export(
        self,
        actor: Principal,
        type_name: str | None = None,
        status: str | None = None,
        include_scopes: bool = False,
    ) -> dict[str, Any]: ...


def batches(ids: set[str]) -> list[list[str]]:
    ordered = sorted(ids)
    return [ordered[i : i + 400] for i in range(0, len(ordered), 400)]


class SqliteGraphStore:
    def __init__(self, db: IndexDB) -> None:
        self.db = db

    @staticmethod
    def _check(db: sqlite3.Connection, ids: list[str], actor: Principal, depth: int) -> None:
        if not 1 <= depth <= 5:
            raise WikiError("E_REQUEST_INVALID", "Глубина графа: 1–5.", status=400)
        for page_id in ids:
            check_id(page_id)
        levels = clearance_values(actor)
        for batch in batches(set(ids)):
            count = db.execute(
                f"SELECT count(*) FROM pages WHERE id IN ({','.join('?' for _ in batch)}) AND sensitivity IN ({','.join('?' for _ in levels)})",
                (*batch, *levels),
            ).fetchone()[0]
            if count != len(batch):
                raise not_found()

    @staticmethod
    def _wave(
        db: sqlite3.Connection,
        frontier: set[str],
        actor: Principal,
        rels: list[str] | None,
        direction: str,
        canonical: bool = False,
    ) -> list[dict[str, Any]]:
        levels = clearance_values(actor)
        result: list[dict[str, Any]] = []
        for batch in batches(frontier):
            queries, values = [], []
            for source, target in (
                [("src", "dst")]
                if direction == "out"
                else [("dst", "src")]
                if direction == "in"
                else [("src", "dst"), ("dst", "src")]
            ):
                query = f"SELECT e.{source} AS src,e.{target} AS dst,e.rel,e.kind FROM edges e JOIN pages p ON p.id=e.{target} WHERE e.{source} IN ({','.join('?' for _ in batch)}) AND p.sensitivity IN ({','.join('?' for _ in levels)})"
                values.extend([*batch, *levels])
                if rels:
                    query += " AND e.rel IN (" + ",".join("?" for _ in rels) + ")"
                    values.extend(rels)
                if canonical:
                    query += " AND (e.kind!='inverse' OR e.rel='conflicts_with')"
                queries.append(query)
            result.extend(
                dict(row)
                for row in db.execute(
                    " UNION ".join(queries) + " ORDER BY src,dst,rel,kind", values
                )
            )
        return result

    def _walk(
        self,
        db: sqlite3.Connection,
        roots: list[str],
        actor: Principal,
        depth: int,
        rels: list[str] | None,
        direction: str,
        canonical: bool = False,
    ) -> tuple[dict[str, int], dict[str, dict[str, Any]]]:
        self._check(db, roots, actor, depth)
        if direction not in ("in", "out", "both"):
            raise WikiError("E_REQUEST_INVALID", "direction: in, out, both.", status=400)
        distances: dict[str, int] = dict.fromkeys(roots, 0)
        parents: dict[str, dict[str, Any]] = {}
        frontier = set(roots)
        for distance in range(1, depth + 1):
            wave = self._wave(db, frontier, actor, rels, direction, canonical)
            frontier = set()
            for edge in wave:
                if edge["dst"] not in distances:
                    distances[edge["dst"]] = distance
                    parents[edge["dst"]] = edge
                    frontier.add(edge["dst"])
            if not frontier:
                break
        return distances, parents

    @staticmethod
    def _nodes(db: sqlite3.Connection, distances: dict[str, int]) -> list[dict[str, Any]]:
        nodes: list[dict[str, Any]] = []
        for batch in batches(set(distances)):
            nodes.extend(
                {**dict(row), "distance": distances[row["id"]]}
                for row in db.execute(
                    f"SELECT id,type,title,summary,status FROM pages WHERE id IN ({','.join('?' for _ in batch)})",
                    batch,
                )
            )
        return sorted(nodes, key=lambda n: (n["distance"], n["id"]))

    @staticmethod
    def _edges(
        db: sqlite3.Connection, ids: set[str], rels: list[str] | None = None
    ) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for batch in batches(ids):
            query = f"SELECT * FROM edges WHERE src IN ({','.join('?' for _ in batch)})"
            values = batch.copy()
            if rels:
                query += " AND rel IN (" + ",".join("?" for _ in rels) + ")"
                values.extend(rels)
            result.extend(dict(row) for row in db.execute(query, values) if row["dst"] in ids)
        return sorted(result, key=lambda e: (e["src"], e["dst"], e["rel"], e["kind"]))

    def neighbors(
        self,
        page_id: str,
        actor: Principal,
        depth: int = 1,
        rels: list[str] | None = None,
        direction: str = "both",
    ) -> dict[str, Any]:
        with self.db.connect() as db:
            distances, _ = self._walk(db, [page_id], actor, depth, rels, direction)
            return {
                "nodes": self._nodes(db, distances),
                "edges": self._edges(db, set(distances), rels),
            }

    def subgraph(
        self, ids: list[str], actor: Principal, rels: list[str] | None = None, depth: int = 1
    ) -> dict[str, Any]:
        with self.db.connect() as db:
            distances, _ = self._walk(db, ids, actor, depth, rels, "both")
            return {
                "nodes": self._nodes(db, distances),
                "edges": self._edges(db, set(distances), rels),
            }

    def path(
        self, source: str, target: str, actor: Principal, max_depth: int = 5
    ) -> dict[str, Any]:
        with self.db.connect() as db:
            self._check(db, [source, target], actor, max_depth)
            distances, parents = self._walk(db, [source], actor, max_depth, None, "both")
        if target not in distances:
            return {"nodes": [], "edges": []}
        ids, result_edges = [target], []
        while ids[-1] != source:
            edge = parents[ids[-1]]
            result_edges.append(edge)
            ids.append(edge["src"])
        return {"nodes": list(reversed(ids)), "edges": list(reversed(result_edges))}

    def impact(
        self, page_id: str, actor: Principal, depth: int = 2, rels: list[str] | None = None
    ) -> dict[str, Any]:
        with self.db.connect() as db:
            distances, parents = self._walk(db, [page_id], actor, depth, rels, "in", canonical=True)
            nodes = [
                {**node, "rel": parents[node["id"]]["rel"]}
                for node in self._nodes(db, distances)
                if node["id"] != page_id
            ]
            return {"id": page_id, "nodes": nodes, "edges": self._edges(db, set(distances), rels)}

    def export(
        self,
        actor: Principal,
        type_name: str | None = None,
        status: str | None = None,
        include_scopes: bool = False,
    ) -> dict[str, Any]:
        levels = clearance_values(actor)
        with self.db.connect() as db:
            rows = db.execute(
                f"SELECT * FROM pages WHERE sensitivity IN ({','.join('?' for _ in levels)}) AND (? IS NULL OR type=?) AND (? IS NULL OR status=?) ORDER BY id",
                (*levels, type_name, type_name, status, status),
            ).fetchall()
            nodes = [
                {key: row[key] for key in ("id", "type", "title", "summary", "status")}
                for row in rows
            ]
            edges = self._edges(db, {node["id"] for node in nodes})
        if include_scopes:
            scopes = set()
            for row in rows:
                for scope in json.loads(row["extra"]).get("applies_to", []):
                    scopes.add(scope)
                    edges.append(
                        {
                            "src": row["id"],
                            "dst": "scope:" + scope,
                            "rel": "applies_to",
                            "kind": "virtual",
                        }
                    )
            nodes.extend(
                {
                    "id": "scope:" + scope,
                    "type": "scope",
                    "title": scope,
                    "summary": scope,
                    "status": "virtual",
                }
                for scope in sorted(scopes)
            )
        return {"nodes": nodes, "edges": edges}


Graph = SqliteGraphStore
