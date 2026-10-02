from typing import Any

from wikiagent.client import WikiClient
from wikiagent.planner.claims import Claim


def collect(client: WikiClient, claim: Claim) -> dict[str, dict[str, Any]]:
    result = client.request(
        "GET",
        "/rules/related",
        params={"q": claim.text[:1000], "impact_terms": ",".join(claim.impact_terms), "limit": 8},
    )
    ids = {p["id"] for p in result["pages"][:8]}
    for rule in result["rules"]:
        ids.add(rule["id"])
        ids.update(p["id"] for p in rule["related"][:4])
        impact = client.request("GET", "/graph/impact/" + rule["id"])
        ids.update(p["id"] for p in impact["nodes"][:4])
    return {page_id: client.request("GET", "/pages/" + page_id) for page_id in sorted(ids)[:20]}
