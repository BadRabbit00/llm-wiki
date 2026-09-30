from __future__ import annotations

from typing import TYPE_CHECKING, Any

from wikisvc.domain.errors import WikiError
from wikisvc.domain.markdown import render
from wikisvc.domain.models import Principal
from wikisvc.domain.validate import parse_page
from wikisvc.services.auth import require_role
from wikisvc.storage.gitrepo import GitRepo
from wikisvc.storage.lock import write_lock
from wikisvc.storage.safefs import SafeFS
from wikisvc.storage.state_db import now

if TYPE_CHECKING:
    from wikisvc.services.runtime import Runtime


def review(
    runtime: Runtime, actor: Principal, page_id: str, verified: bool, reason: str = ""
) -> dict[str, Any]:
    require_role(actor, "reviewer")
    from wikisvc.domain.secrets import secret_kinds

    if not verified and (not reason.strip() or len(reason) > 1000 or secret_kinds(reason)):
        raise WikiError(
            "E_REQUEST_INVALID", "Нужна причина без секретов (до 1000 символов).", status=400
        )
    config = runtime.settings
    with write_lock(config.state_dir, config.lock_timeout):
        repo = GitRepo(config.wiki_root)
        repo.ensure_main()
        page = runtime.pages.page(page_id, actor)
        fs = SafeFS(config.wiki_root)
        page = parse_page(fs.read(page.path), page.path)
        page.frontmatter.status = "verified" if verified else "outdated"
        if verified:
            page.frontmatter.verified_at = now()
            page.frontmatter.verified_by = actor.name
        fs.write(page.path, render(page.frontmatter.model_dump(mode="json"), page.body_md))
        repo.commit(
            f"{'Verify' if verified else 'Mark outdated'} {page_id}"
            + (": " + reason if reason else ""),
            actor.name,
        )
        runtime.indexer.reindex([page.path])
        runtime.state.audit(
            actor.name, "page.verify" if verified else "page.mark-outdated", page_id
        )
    return runtime.pages.serialize(runtime.pages.page(page_id, actor))
