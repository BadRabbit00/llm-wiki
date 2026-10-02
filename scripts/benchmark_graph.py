"""Reproducible graph benchmark: nix develop -c python scripts/benchmark_graph.py."""

import json
import random
import tempfile
import time
from pathlib import Path

from wikisvc.domain.models import Principal
from wikisvc.index.db import IndexDB
from wikisvc.index.graph import SqliteGraphStore


def benchmark(directory: Path) -> float:
    db = IndexDB(directory)
    rng = random.Random(42)
    with db.connect() as connection:
        for n in range(2000):
            connection.execute(
                "INSERT INTO pages VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    f"rule-bench-{n}",
                    "rule",
                    f"Rule {n}",
                    "Benchmark rule summary",
                    "draft",
                    "internal",
                    f"{n}.md",
                    "[]",
                    "[]",
                    "{}",
                    "",
                    str(n),
                    "2026-01-01",
                    "2026-01-01",
                    None,
                    None,
                    "{}",
                ),
            )
        edges: set[tuple[str, str, str, str]] = set()
        while len(edges) < 10000:
            a, b = rng.sample(range(2000), 2)
            edges.add((f"rule-bench-{a}", f"rule-bench-{b}", "depends_on", "frontmatter"))
        connection.executemany("INSERT INTO edges VALUES (?,?,?,?)", sorted(edges))
    actor = Principal(name="bench", role="reader", clearance="internal")
    graph = SqliteGraphStore(db)
    times = []
    for _ in range(5):
        started = time.perf_counter()
        result = graph.neighbors("rule-bench-0", actor, depth=3)
        times.append((time.perf_counter() - started) * 1000)
    elapsed = sorted(times)[len(times) // 2]
    print(
        json.dumps(
            {
                "pages": 2000,
                "edges": 10000,
                "depth": 3,
                "median_ms": round(elapsed, 2),
                "visited": len(result["nodes"]),
            }
        )
    )
    return elapsed


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as directory:
        if benchmark(Path(directory)) > 100:
            raise SystemExit("Graph traversal exceeds 100 ms")
