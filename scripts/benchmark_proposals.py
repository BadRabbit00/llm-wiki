"""Run with `nix develop -c python scripts/benchmark_proposals.py [page-count]`."""

import json
import sys
import tempfile
import time
from pathlib import Path

from wikisvc.config import Settings
from wikisvc.domain.markdown import render
from wikisvc.domain.models import Principal
from wikisvc.services.initialize import initialize
from wikisvc.services.runtime import Runtime
from wikisvc.storage.gitrepo import GitRepo
from wikisvc.storage.safefs import SafeFS


def main() -> None:
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 1500
    with tempfile.TemporaryDirectory(prefix="wikisvc-benchmark-") as temporary:
        root = Path(temporary)
        config = Settings(
            wiki_root=root / "wiki", state_dir=root / "state", index_dir=root / "index"
        )
        initialize(config.wiki_root)
        fs = SafeFS(config.wiki_root)
        for number in range(count):
            metadata = {
                "id": f"term-bench-{number}",
                "type": "term",
                "title": f"Термин {number}",
                "summary": "Описание понятия компании для проверки масштаба вики.",
                "status": "draft",
                "created": "2026-01-01",
                "updated": "2026-01-01",
            }
            fs.write(
                f"wiki/domain/glossary/bench-{number}.md",
                render(
                    metadata, "## Определение\n\nОписание предметной области и регламента компании."
                ),
            )
        GitRepo(config.wiki_root).commit("Benchmark corpus", "fixture")
        rt = Runtime(config)
        rt.reindex()
        writer = Principal(name="author", role="writer", clearance="restricted")
        reviewer = Principal(name="reviewer", role="reviewer", clearance="restricted")
        timings = []
        for iteration in range(3):
            pid = rt.proposals.create(writer, "Benchmark proposal")["pid"]
            page = rt.pages.page("term-bench-0", writer)
            start = time.perf_counter()
            rt.proposals.put(
                pid,
                page.id,
                writer,
                page.frontmatter.model_dump(),
                page.body_md + f"\nIteration {iteration}.",
                page.version,
            )
            put = time.perf_counter()
            rt.proposals.submit(pid, writer)
            submit = time.perf_counter()
            rt.proposals.decide(pid, reviewer, "accepted")
            accept = time.perf_counter()
            timings.append(
                {
                    "put": round(put - start, 3),
                    "submit": round(submit - put, 3),
                    "accept": round(accept - submit, 3),
                }
            )
        print(json.dumps({"pages": count, "seconds": timings}, indent=2))


if __name__ == "__main__":
    main()
