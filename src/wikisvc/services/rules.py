from typing import TYPE_CHECKING, Any

from wikisvc.domain.errors import WikiError, not_found
from wikisvc.domain.models import Page, Principal
from wikisvc.index.indexer import row_page
from wikisvc.services.auth import can_read

if TYPE_CHECKING:
    from wikisvc.services.runtime import Runtime

RULE_RELS = [
    "refines",
    "refined_by",
    "conflicts_with",
    "supersedes",
    "superseded_by",
    "depends_on",
    "required_by",
]
IMPACT_RELS = ["refines", "conflicts_with", "supersedes", "depends_on", "governed_by", "implements"]


def brief(page: Page) -> dict[str, Any]:
    return {
        "id": page.id,
        "title": page.frontmatter.title,
        "summary": page.frontmatter.summary,
        **{
            key: (page.frontmatter.model_extra or {}).get(key)
            for key in ("category", "level", "lifecycle", "applies_to", "origin", "enforced_by")
        },
    }


class Rules:
    def __init__(self, runtime: "Runtime") -> None:
        self.rt = runtime

    def get(self, page_id: str, actor: Principal) -> dict[str, Any]:
        page = self.rt.pages.page(page_id, actor)
        if page.frontmatter.type != "rule":
            raise not_found()
        result = self.rt.pages.get(page_id, actor)
        assert isinstance(result, dict)
        graph = self.rt.graph.neighbors(page_id, actor, rels=RULE_RELS)
        related, omitted, used = [], [], 0
        for node in graph["nodes"]:
            if node["id"] == page_id or node["type"] != "rule":
                continue
            item = brief(self.rt.pages.page(node["id"], actor))
            item["rels"] = sorted(
                {e["rel"] for e in graph["edges"] if {e["src"], e["dst"]} == {page_id, node["id"]}}
            )
            cost = self.rt.policies.tokens(
                f"{item['id']} {item['level']} {item['lifecycle']} {','.join(item['rels'])}: {item['summary']}"
            )
            if used + cost <= 600:
                related.append(item)
                used += cost
            else:
                omitted.append(node["id"])
        return {
            **result,
            "related": related,
            "related_tokens": used,
            "related_omitted_ids": omitted,
        }

    def related(
        self,
        query: str,
        actor: Principal,
        scopes: list[str] | None = None,
        limit: int = 10,
        impact_terms: list[str] | None = None,
    ) -> dict[str, Any]:
        if not 1 <= limit <= 50:
            raise WikiError("E_REQUEST_INVALID", "limit: 1–50.", status=400)
        if scopes and set(scopes) - set(self.rt.registry.scopes):
            raise WikiError("E_SCOPE_UNKNOWN", "Неизвестная область применения.", status=400)
        matches = self.rt.search.search(
            query, actor, type_name="rule", k=50, lifecycle=["candidate", "active", "deprecated"]
        )["results"]
        rules: list[dict[str, Any]] = []
        pages: dict[str, dict[str, Any]] = {}
        for hit in matches:
            item = brief(self.rt.pages.page(hit["id"], actor))
            if (
                scopes
                and "*" not in item["applies_to"]
                and not set(scopes) & set(item["applies_to"])
            ):
                continue
            neighbors = self.rt.graph.neighbors(hit["id"], actor, rels=RULE_RELS)
            item.update(
                score_rank=len(rules) + 1,
                via=hit["via"],
                related=[
                    {"id": n["id"], "summary": n["summary"]}
                    for n in neighbors["nodes"]
                    if n["id"] != hit["id"] and n["type"] == "rule"
                ],
            )
            rules.append(item)
            for node in self.rt.graph.impact(hit["id"], actor, rels=IMPACT_RELS)["nodes"]:
                if node["type"] in ("pattern", "playbook", "adr", "app"):
                    pages[node["id"]] = {k: node[k] for k in ("id", "type", "title", "summary")}
            if len(rules) >= limit:
                break
        for term in [query, *(impact_terms or [])]:
            for hit in self.rt.search.search(term, actor, k=50)["results"]:
                if hit["type"] in ("pattern", "playbook", "adr", "app"):
                    pages[hit["id"]] = {k: hit[k] for k in ("id", "type", "title", "summary")}
        return {"query": query, "rules": rules, "pages": list(pages.values())}

    def proposal_impact(self, pid: str, actor: Principal) -> dict[str, Any]:
        proposal = self.rt.proposals._proposal(pid, actor)
        changes = self.rt.proposals._changes(proposal)
        pages, scopes, changed = {}, set(), set()
        for before, after in changes:
            for page in (before, after):
                if page:
                    changed.add(page.id)
                    scopes.update((page.frontmatter.model_extra or {}).get("applies_to", []))
            if before:
                for node in self.rt.graph.impact(before.id, actor, rels=IMPACT_RELS)["nodes"]:
                    pages[node["id"]] = node
        rules = []
        with self.rt.index.connect() as db:
            for row in db.execute("SELECT * FROM pages WHERE type='rule'"):
                page = row_page(row)
                extra = page.frontmatter.model_extra or {}
                applies = set(extra.get("applies_to", []))
                if (
                    can_read(actor, row["sensitivity"])
                    and page.id not in changed
                    and extra.get("lifecycle") == "active"
                    and (scopes & applies or ("*" in applies and scopes) or "*" in scopes)
                ):
                    rules.append(brief(page))
        profiles = [
            name
            for name, profile in self.rt.registry.profiles.items()
            if set(profile.scopes) & scopes or "*" in scopes
        ]
        return {"pid": pid, "pages": list(pages.values()), "rules": rules, "profiles": profiles}
