from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from wikisvc.domain.markdown import edges
from wikisvc.domain.models import LintIssue, Principal
from wikisvc.domain.validate import issue
from wikisvc.index.indexer import row_page
from wikisvc.services.auth import can_read

if TYPE_CHECKING:
    from wikisvc.services.runtime import Runtime


def timestamp(value: str) -> datetime:
    date = datetime.fromisoformat(value)
    return date.replace(tzinfo=UTC) if date.tzinfo is None else date


class Lint:
    def __init__(self, runtime: Runtime) -> None:
        self.rt = runtime

    def run(self, actor: Principal) -> list[LintIssue]:
        with self.rt.index.connect() as db:
            pages = {
                page.id: page
                for row in db.execute("SELECT * FROM pages ORDER BY id")
                if can_read(actor, row["sensitivity"])
                for page in [row_page(row)]
            }
            issues = [
                LintIssue.model_validate_json(row["data"])
                for row in db.execute("SELECT * FROM issues ORDER BY page,data")
                if row["page"] in pages or actor.clearance == "restricted"
            ]
        issues.extend(self.rt.extractions.citation_issues(list(pages.values())))
        issues.extend(
            issue(
                "E_TEMPLATE_INVALID",
                f"schema/project-templates/{template_id}.yaml",
                reason,
                "Исправьте шаблон проекта или его ссылки на профили и scopes.",
            )
            for template_id, reason in self.rt.registry.invalid_project_templates.items()
        )
        all_edges = [edge for page in pages.values() for edge in edges(page) if edge.dst in pages]
        linked = {
            page_id
            for edge in all_edges
            if edge.src != edge.dst
            and pages[edge.src].frontmatter.type != "source"
            and pages[edge.dst].frontmatter.type != "source"
            for page_id in (edge.src, edge.dst)
        }
        for page in pages.values():
            if page.id not in linked and page.frontmatter.type != "rule":
                issues.append(
                    issue(
                        "W_ORPHAN",
                        page.id,
                        "У страницы нет связей с другими страницами (кроме источников).",
                    )
                )
        for edge in all_edges:
            source, target = pages[edge.src].frontmatter, pages[edge.dst].frontmatter
            if (
                source.status == "verified"
                and source.verified_at
                and edge.rel
                in {"depends_on", "uses", "reads", "writes", "integrates_with", "governed_by"}
                and timestamp(target.updated) > timestamp(source.verified_at)
            ):
                issues.append(
                    issue(
                        "W_STALE_DEPENDENCY",
                        edge.src,
                        f"Зависимость {edge.dst} обновлена после проверки страницы.",
                        "Прочитайте зависимость, обновите страницу через proposal и запросите проверку.",
                    )
                )
            if source.status != "outdated" and (
                target.status == "outdated"
                or (target.model_extra or {}).get("adr_status") == "superseded"
            ):
                issues.append(
                    issue(
                        "W_SUPERSEDED_LINKED",
                        edge.src,
                        f"Страница ссылается на устаревшую {edge.dst}.",
                    )
                )
        if actor.clearance == "restricted":
            issues.extend(
                issue(
                    "W_PENDING_SOURCE",
                    raw["path"],
                    "Источник ещё не обработан.",
                    "Создайте source и обновите знания по сценарию ingest.",
                )
                for raw in self.rt.raw.records(actor, pending=True)
            )
        unique = {(value.code, value.page, value.message): value for value in issues}
        for profile in self.rt.registry.profiles:
            if self.rt.policies.compile(actor, profile=profile, count_usage=False)["over_budget"]:
                problem = issue(
                    "W_PROFILE_OVER_BUDGET",
                    None,
                    f"Обязательные правила профиля {profile} превышают бюджет.",
                )
                unique[(problem.code, problem.page, problem.message)] = problem
        return sorted(
            unique.values(),
            key=lambda item: (item.severity != "error", item.code, item.page or "", item.message),
        )

    def stats(self, actor: Principal) -> dict[str, Any]:
        graph = self.rt.graph.export(actor)
        issues = self.run(actor)
        with self.rt.index.connect() as db:
            rows = [
                row
                for row in db.execute("SELECT * FROM delivery_stats")
                if can_read(actor, row["clearance"])
            ]
        return {
            "pages": len(graph["nodes"]),
            "by_type": dict(Counter(page["type"] for page in graph["nodes"])),
            "by_status": dict(Counter(page["status"] for page in graph["nodes"])),
            "edges": len(graph["edges"]),
            "orphans": sum(i.code == "W_ORPHAN" for i in issues),
            "pending_sources": sum(i.code == "W_PENDING_SOURCE" for i in issues)
            if actor.clearance == "restricted"
            else None,
            "delivery": {
                "requests": len(rows),
                "chars_available": sum(row["chars_available"] for row in rows),
                "chars_delivered": sum(row["chars_delivered"] for row in rows),
                "pages_truncated": sum(row["pages_truncated"] for row in rows),
                "truncated_requests": sum(row["pages_truncated"] > 0 for row in rows),
            },
        }
