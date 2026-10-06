from collections import Counter
from typing import Any

from wikiagent.client import WikiClient
from wikisvc.domain.validate import overlaps


def pairs(
    client: WikiClient, pages: dict[str, dict[str, Any]], changed: set[str], full: bool, k: int
) -> list[tuple[str, str]]:
    selected = set(pages) if full else set(changed)
    for page_id in sorted(changed):
        graph = client.request(
            "GET",
            "/graph/neighbors/" + page_id,
            params={"rels": "refines,conflicts_with,supersedes,depends_on,refined_by,required_by"},
        )
        selected.update(n["id"] for n in graph["nodes"] if n["id"] in pages)
    result = set()
    for page_id in sorted(selected):
        page = pages[page_id]
        candidates: list[str] = []
        graph = client.request(
            "GET",
            "/graph/neighbors/" + page_id,
            params={"rels": "refines,conflicts_with,supersedes,depends_on,refined_by,required_by"},
        )
        candidates.extend(n["id"] for n in graph["nodes"] if n["id"] != page_id)
        hits = client.request(
            "GET",
            "/search",
            params={
                "q": page["summary"],
                "type": "rule",
                "k": k,
                "lifecycle": "candidate,active,deprecated",
            },
        )
        candidates.extend(p["id"] for p in hits["results"] if p["id"] != page_id)
        candidates.extend(
            other
            for other, p in sorted(pages.items())
            if other != page_id
            and p["category"] == page["category"]
            and overlaps(p["applies_to"], page["applies_to"])
        )
        for other in list(dict.fromkeys(candidates))[:20]:
            if other in pages and (full or page_id in changed or other in changed):
                a, b = sorted((page_id, other))
                result.add((a, b))
    ordered = sorted(
        result, key=lambda pair: (not any(pages[p]["level"] == "must" for p in pair), pair)
    )
    counts: Counter[str] = Counter()
    bounded = []
    for a, b in ordered:
        if counts[a] < 20 and counts[b] < 20:
            bounded.append((a, b))
            counts.update((a, b))
    return bounded
