from __future__ import annotations

from typing import TYPE_CHECKING, Any

from wikisvc.domain.errors import WikiError
from wikisvc.domain.markdown import render
from wikisvc.domain.models import Page, Principal
from wikisvc.domain.validate import parse_page
from wikisvc.services.auth import require_human
from wikisvc.storage.gitrepo import GitRepo
from wikisvc.storage.lock import write_lock
from wikisvc.storage.safefs import SafeFS
from wikisvc.storage.state_db import now

if TYPE_CHECKING:
    from wikisvc.services.runtime import Runtime


def review(
    runtime: Runtime, actor: Principal, page_id: str, verified: bool, reason: str = ""
) -> dict[str, Any]:
    require_human(actor)
    from wikisvc.domain.secrets import secret_kinds

    if not verified and (not reason.strip() or len(reason) > 1000 or secret_kinds(reason)):
        raise WikiError(
            "E_REQUEST_INVALID", "Нужна причина без секретов (до 1000 символов).", status=400
        )
    config = runtime.settings
    with write_lock(config.state_dir, config.lock_timeout):
        repo = GitRepo(config.wiki_root)
        repo.ensure_main()
        runtime.sync_index()
        page = runtime.pages.page(page_id, actor)
        fs = SafeFS(config.wiki_root)
        page = parse_page(fs.read(page.path), page.path)
        page.frontmatter.status = "verified" if verified else "outdated"
        if verified:
            page.frontmatter.verified_at = now()
            page.frontmatter.verified_by = actor.identity
        if page.frontmatter.type == "rule":
            from wikisvc.domain.validate import require_valid, validate_page

            require_valid(validate_page(page, runtime.registry, config.secret_entropy_threshold))
        with repo.transaction([page.path]):
            fs.write(page.path, render(page.frontmatter.model_dump(mode="json"), page.body_md))
            repo.commit(
                f"{'Verify' if verified else 'Mark outdated'} {page_id}"
                + (": " + reason if reason else ""),
                actor.name,
                [page.path],
            )
        runtime.indexer.reindex([page.path])
        runtime.state.audit(
            actor.name, "page.verify" if verified else "page.mark-outdated", page_id
        )
    return runtime.pages.serialize(runtime.pages.page(page_id, actor))


def rule_decision(page: Page, actor: Principal, operation: str, values: dict[str, Any]) -> Page:
    """Pure transformation shared by direct review and atomic proposal acceptance."""
    from wikisvc.services.auth import require_human

    require_human(actor)
    if page.frontmatter.type != "rule":
        raise WikiError("E_RULE_FIELDS", "Операция доступна только для rule.")
    data = page.frontmatter.model_dump(mode="json")
    if operation == "promote":
        if set(values) - {"level", "priority", "applies_to", "owner", "enforced_by"}:
            raise WikiError("E_REQUEST_INVALID", "Неизвестные поля promote.", status=400)
        if values.get("level", "should") not in ("must", "should"):
            raise WikiError("E_RULE_FIELDS", "Повышение: level must или should.")
        data.update(values)
        data.update(
            lifecycle="active",
            level=values.get("level", "should"),
            status="verified",
            verified_by=actor.identity,
            verified_at=now(),
        )
        data.pop("deprecated_reason", None)
    elif operation == "deprecate":
        reason = values.get("reason")
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 200:
            raise WikiError(
                "E_REQUEST_INVALID", "Нужна причина снятия (1–200 символов).", status=400
            )
        data.update(lifecycle="deprecated", deprecated_reason=reason)
    else:
        raise ValueError("Unknown rule operation")
    data["updated"] = now()
    return parse_page(render(data, page.body_md), page.path)


def review_rule(
    runtime: Runtime, actor: Principal, page_id: str, operation: str, values: dict[str, Any]
) -> dict[str, Any]:
    from wikisvc.domain.validate import require_valid, validate_set
    from wikisvc.services.auth import require_human
    from wikisvc.services.generators import generate

    require_human(actor)
    config = runtime.settings
    with write_lock(config.state_dir, config.lock_timeout):
        repo = GitRepo(config.wiki_root)
        repo.ensure_main()
        runtime.sync_index()
        page = rule_decision(runtime.pages.page(page_id, actor), actor, operation, values)
        prior = runtime.indexer.pages()
        baseline = {
            (i.code, i.page, i.message)
            for i in validate_set(prior, runtime.registry)
            if i.severity == "error" and i.page != page_id
        }
        merged = [p for p in prior if p.id != page_id] + [page]
        issues = [
            i
            for i in validate_set(merged, runtime.registry)
            if (i.code, i.page, i.message) not in baseline
        ]
        require_valid(issues)
        require_valid([i for i in runtime.extractions.citation_issues(merged) if i.page == page_id])
        paths = [page.path, "wiki/index.md", "wiki/log.md"]
        with repo.transaction(paths):
            SafeFS(config.wiki_root).write(
                page.path, render(page.frontmatter.model_dump(mode="json"), page.body_md)
            )
            generate(config.wiki_root, f"{operation}: {page_id}", actor.identity, merged)
            repo.commit(f"{operation.capitalize()} {page_id}", actor.name, paths)
        runtime.indexer.reindex(paths)
        runtime.state.audit(actor.name, "rule." + operation, page_id)
        dependencies = runtime.graph.impact(page_id, actor)["nodes"]
    return {
        **runtime.pages.serialize(page),
        "warnings": [i.model_dump() for i in issues if i.severity != "error" and i.page == page_id],
        "dependencies": dependencies,
    }
