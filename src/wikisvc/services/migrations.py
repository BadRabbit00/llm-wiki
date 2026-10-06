"""Explicit administrative schema upgrades and proposal-based content migration."""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from wikisvc.domain.errors import WikiError
from wikisvc.domain.markdown import load_yaml, render, sections
from wikisvc.domain.models import Principal
from wikisvc.index.indexer import read_pages
from wikisvc.services.auth import can_read, require_role
from wikisvc.storage.gitrepo import GitRepo
from wikisvc.storage.lock import write_lock
from wikisvc.storage.safefs import SafeFS

if TYPE_CHECKING:
    from wikisvc.services.runtime import Runtime

LEGACY = {
    "convention": "code-style",
    "stack": "stack",
    "security": "security",
    "testing": "testing",
}


def yaml_text(value: Any) -> str:
    import io

    from ruamel.yaml import YAML

    stream = io.StringIO()
    YAML().dump(value, stream)
    return stream.getvalue()


def upgrade_schema(
    rt: Runtime, actor: Principal, refresh_instructions: bool = False
) -> dict[str, Any]:
    require_role(actor, "admin")
    with write_lock(rt.settings.state_dir, rt.settings.lock_timeout):
        repo, fs = GitRepo(rt.settings.wiki_root), SafeFS(rt.settings.wiki_root)
        repo.ensure_main()
        template = SafeFS(Path(__file__).resolve().parents[1] / "template")
        writes = {
            p: template.read(p) for p in template.files("schema/**/*") if not fs.path(p).exists()
        }
        if refresh_instructions:
            for path in ["AGENTS.md", *template.files("schema/workflows/*.md")]:
                writes[path] = template.read(path)
        deletes = [
            f"schema/page-types/{kind}.yaml"
            for kind in LEGACY
            if fs.path(f"schema/page-types/{kind}.yaml").exists()
        ]
        rels = load_yaml(fs.read("schema/relations.yaml"))
        defaults = load_yaml(template.read("schema/relations.yaml"))
        for name, definition in defaults.items():
            if name not in rels:
                rels[name] = definition
            else:
                for side in ("from", "to"):
                    rels[name][side] = list(
                        dict.fromkeys(
                            "rule" if kind in LEGACY else kind for kind in rels[name].get(side, [])
                        )
                    )
        writes["schema/relations.yaml"] = yaml_text(rels)
        source = load_yaml(fs.read("schema/page-types/source.yaml"))
        source["extra_fields"].update(
            load_yaml(template.read("schema/page-types/source.yaml"))["extra_fields"]
        )
        writes["schema/page-types/source.yaml"] = yaml_text(source)
        writes = {
            p: content
            for p, content in writes.items()
            if not fs.path(p).exists() or fs.read(p) != content
        }
        paths = [*writes, *deletes]
        if not paths:
            return {"commit": repo.head(), "updated": [], "removed": []}
        with repo.transaction(paths):
            for path, content in writes.items():
                fs.write(path, content)
            for path in deletes:
                fs.remove(path)
            commit = repo.commit("Upgrade policy schema", actor.name, paths)
        rt.reindex()
        rt.state.audit(actor.name, "schema.upgrade", commit)
        return {"commit": commit, "updated": sorted(writes), "removed": deletes}


def migrate_rules(rt: Runtime, actor: Principal, dry_run: bool = True) -> dict[str, Any]:
    require_role(actor, "writer")
    pages, _ = read_pages(rt.settings.wiki_root)
    mapping = {p.id: "rule-" + p.id for p in pages if p.frontmatter.type in LEGACY}
    changes = []
    for page in pages:
        metadata, body = page.frontmatter.model_dump(mode="json"), page.body_md
        old_path = page.path
        if page.id in mapping:
            definition = next((s for s in sections(body) if s.heading == "Правило"), None)
            text = (
                body[definition.body_start : definition.end].strip()
                if definition
                else metadata["summary"]
            )
            thesis = re.split(r"(?<=[.!?])\s+", text)[0].replace("\n", " ")[:160]
            if len(thesis) < 20:
                thesis = metadata["summary"][:160]
            metadata.update(
                id=mapping[page.id],
                type="rule",
                category=LEGACY[page.frontmatter.type],
                summary=thesis,
                origin="team",
                level="idea",
                lifecycle="candidate",
                applies_to=["*"],
                priority=3,
                status="draft",
                verified_by=None,
                verified_at=None,
            )
            allowed = rt.registry.page_type("rule").extra_fields
            for key in page.frontmatter.model_extra or {}:
                if key not in allowed:
                    metadata.pop(key, None)
            body = (
                "## Правило\n\n"
                + text
                + "\n\n## Обоснование\n\nПеренесено из прежнего свода правил; требуется ревью.\n\n## Примеры\n\n"
                + re.sub(r"(?m)^#{1,6}\s+(.+)$", r"**\1**", body)
            )
            path = "wiki/rules/" + mapping[page.id][5:] + ".md"
        else:
            path = old_path
            if metadata["type"] == "source":
                metadata.setdefault("kind", "doc")
        rendered = render(metadata, body)
        for old, new in mapping.items():
            rendered = re.sub(r"(?<![\w-])" + re.escape(old) + r"(?![\w-])", new, rendered)
        if rendered == render(page.frontmatter.model_dump(mode="json"), page.body_md):
            continue
        if not can_read(actor, page.frontmatter.sensitivity):
            raise WikiError(
                "E_FORBIDDEN",
                "Для миграции требуется доступ ко всем затронутым страницам.",
                status=403,
            )
        changes.append({"before": old_path, "path": path, "text": rendered})
    result: dict[str, Any] = {
        "dry_run": dry_run,
        "mapping": mapping,
        "pages": [{k: c[k] for k in ("before", "path")} for c in changes],
    }
    if dry_run or not changes:
        return result
    created = rt.proposals.create(actor, "Migrate legacy rules to candidates")
    pid = created["pid"]
    with write_lock(rt.settings.state_dir, rt.settings.lock_timeout):
        proposal = rt.proposals._proposal(pid, actor, editing=True)
        fs, repo = SafeFS(rt.proposals.worktree(pid)), GitRepo(rt.proposals.worktree(pid))
        paths = sorted({p for c in changes for p in (c["before"], c["path"])})
        with repo.transaction(paths):
            for change in changes:
                fs.write(change["path"], change["text"])
                if change["before"] != change["path"]:
                    fs.remove(change["before"])
            repo.commit("Migrate legacy rule pages", actor.name, paths)
        rt.proposals._snapshot(proposal)
        rt.proposals._edited(proposal, actor)
    result.update(proposal=pid, validation=rt.proposals.validate(pid, actor))
    return result
