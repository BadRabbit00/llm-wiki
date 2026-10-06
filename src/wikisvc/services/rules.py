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
            if after:
                for rel, targets in after.frontmatter.relations.items():
                    if rel not in IMPACT_RELS:
                        continue
                    for target in targets:
                        try:
                            for node in self.rt.graph.impact(target, actor, rels=IMPACT_RELS)[
                                "nodes"
                            ]:
                                pages[node["id"]] = node
                        except WikiError as exc:
                            if exc.status != 404:
                                raise
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

    def list_rules(
        self,
        actor: Principal,
        category: str | None = None,
        level: str | None = None,
        lifecycle: list[str] | None = None,
        applies_to: list[str] | None = None,
        origin: str | None = None,
        source: str | None = None,
        q: str | None = None,
        sort: str = "id",
        limit: int = 50,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        from wikisvc.domain.validate import overlaps
        from wikisvc.index.search import lifecycles
        from wikisvc.services.pages import paginate

        allowed = lifecycles(lifecycle)
        if sort not in ("id", "priority", "updated", "delivered", "opened", "violations"):
            raise WikiError("E_REQUEST_INVALID", "Неизвестный порядок правил.", status=400)
        matching = (
            {
                h["id"]
                for h in self.rt.search.search(q, actor, type_name="rule", k=50, lifecycle=allowed)[
                    "results"
                ]
            }
            if q
            else None
        )
        usage = {
            row["rule_id"]: row
            for row in self.rt.state.rows(
                "SELECT rule_id,SUM(delivered) delivered,SUM(opened) opened,SUM(violations) violations FROM rule_usage GROUP BY rule_id"
            )
        }
        result = []
        with self.rt.index.connect() as db:
            for row in db.execute("SELECT * FROM pages WHERE type='rule' ORDER BY id"):
                if not can_read(actor, row["sensitivity"]):
                    continue
                page = row_page(row)
                item = brief(page)
                extra = page.frontmatter.model_extra or {}
                if (
                    item["lifecycle"] not in allowed
                    or (category and item["category"] != category)
                    or (level and item["level"] != level)
                    or (applies_to and not overlaps(applies_to, item["applies_to"]))
                    or (origin and item["origin"] != origin)
                    or (source and source not in page.frontmatter.sources)
                    or (matching is not None and page.id not in matching)
                ):
                    continue
                item.update(
                    version=page.version,
                    sources=page.frontmatter.sources,
                    priority=extra.get("priority", 3),
                    updated=page.frontmatter.updated,
                    **{
                        key: usage.get(page.id, {}).get(key, 0)
                        for key in ("delivered", "opened", "violations")
                    },
                )
                result.append(item)
        result.sort(
            key=lambda p: (p[sort], p["id"]),
            reverse=sort in ("updated", "delivered", "opened", "violations"),
        )
        return paginate(result, limit, cursor)

    def stats(self, actor: Principal, days: int = 30) -> dict[str, Any]:
        from datetime import UTC, datetime, timedelta

        from wikisvc.services.auth import require_role

        require_role(actor, "reviewer")
        if not 1 <= days <= 3650:
            raise WikiError("E_REQUEST_INVALID", "days: 1–3650.", status=400)
        start = (datetime.now(UTC) - timedelta(days=days - 1)).date().isoformat()
        usage = {
            row["rule_id"]: row
            for row in self.rt.state.rows(
                "SELECT rule_id,SUM(delivered) delivered,SUM(opened) opened,SUM(violations) violations FROM rule_usage WHERE day>=? GROUP BY rule_id",
                (start,),
            )
        }
        rows = []
        for page in self.rt.indexer.pages():
            if page.frontmatter.type == "rule" and can_read(actor, page.frontmatter.sensitivity):
                rows.append(
                    {
                        **brief(page),
                        **{
                            k: usage.get(page.id, {}).get(k, 0)
                            for k in ("delivered", "opened", "violations")
                        },
                    }
                )
        return {
            "days": days,
            "items": rows,
            "never_opened": [p["id"] for p in rows if p["delivered"] and not p["opened"]],
            "often_violated": [p["id"] for p in rows if p["violations"] >= 3],
        }

    def violations(self, actor: Principal, items: list[dict[str, str]]) -> dict[str, int]:
        from wikisvc.domain.secrets import secret_kinds
        from wikisvc.services.auth import require_role
        from wikisvc.storage.lock import write_lock
        from wikisvc.storage.state_db import now

        require_role(actor, "writer")
        with write_lock(self.rt.settings.state_dir, self.rt.settings.lock_timeout):
            for item in items:
                if self.rt.pages.page(item["rule_id"], actor).frontmatter.type != "rule":
                    raise not_found()
                if secret_kinds(
                    item["note"] + "\n" + item["ref"], self.rt.settings.secret_entropy_threshold
                ):
                    raise WikiError("E_SECRET_DETECTED", "Нарушение содержит возможный секрет.")
            with self.rt.state.connect() as db:
                for item in items:
                    db.execute(
                        "INSERT INTO violations VALUES (?,?,?,?,?)",
                        (item["rule_id"], item["note"], item["ref"], actor.name, now()),
                    )
                    db.execute(
                        "INSERT INTO rule_usage(rule_id,day,violations) VALUES (?,?,1) ON CONFLICT(rule_id,day) DO UPDATE SET violations=violations+1",
                        (item["rule_id"], now()[:10]),
                    )
        return {"recorded": len(items)}
