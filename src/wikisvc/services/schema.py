from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from wikisvc.domain.errors import WikiError
from wikisvc.domain.ids import DOMAIN_PATH
from wikisvc.domain.markdown import load_yaml
from wikisvc.domain.models import Principal
from wikisvc.index.indexer import read_pages
from wikisvc.services.auth import require_role
from wikisvc.storage.gitrepo import GitRepo
from wikisvc.storage.lock import write_lock
from wikisvc.storage.safefs import SafeFS
from wikisvc.storage.schema import load_domains

if TYPE_CHECKING:
    from wikisvc.services.runtime import Runtime

KB_KINDS = ("topics", "facts", "tech", "questions")
DOMAINS_FILE = "schema/domains.yaml"


def yaml_text(value: Any) -> str:
    import io

    from ruamel.yaml import YAML

    stream = io.StringIO()
    YAML().dump(value, stream)
    return stream.getvalue()


def kb_missing(fs: SafeFS, domain: str) -> dict[str, str]:
    """Empty `.gitkeep` writes for kb directories of `domain` that are absent or empty."""
    return {
        path: ""
        for path in kb_keepfiles(domain)
        if not (fs.path(path).parent.is_dir() and any(fs.path(path).parent.iterdir()))
    }


def with_scope(raw: str, value: str) -> str | None:
    """`scopes.yaml` text with `value` added to either format; None if already present."""
    data = load_yaml(raw) or []
    if isinstance(data, dict):
        values = data["values"] = data.get("values") or []
    else:
        values = data
    if value in values:
        return None
    values.append(value)
    return yaml_text(data)


def kb_keepfiles(domain: str) -> list[str]:
    """`.gitkeep` paths holding the empty knowledge-base directories of one domain."""
    return [f"wiki/kb/{domain}/{kind}/.gitkeep" for kind in KB_KINDS]


# doc: CLS-wikisvc-core.Schema
class Schema:
    def __init__(self, runtime: Runtime) -> None:
        self.rt = runtime

    # doc: FMT-wikisvc-core.workflow
    def instructions(self) -> dict[str, str]:
        fs = SafeFS(self.rt.settings.wiki_root)
        return {
            "instructions": "\n\n".join(
                fs.read(path) for path in ["AGENTS.md", *fs.files("schema/workflows/*.md")]
            )
        }

    def add_domain(self, path: str, description: str, actor: Principal) -> dict[str, str]:
        """Extend the domain tree (admin only); repeating the call changes nothing."""
        require_role(actor, "admin")
        if not DOMAIN_PATH.fullmatch(path):
            raise WikiError("E_DOMAIN_UNKNOWN", "Путь домена должен иметь вид lang/zig.")
        config = self.rt.settings
        with write_lock(config.state_dir, config.lock_timeout):
            repo, fs = GitRepo(config.wiki_root), SafeFS(config.wiki_root)
            repo.ensure_main()
            domains = load_domains(fs)
            if "/" in path and path.rsplit("/", 1)[0] not in domains:
                raise WikiError(
                    "E_DOMAIN_UNKNOWN",
                    "Родитель домена должен быть отдельной строкой schema/domains.yaml.",
                )
            writes: dict[str, str] = {}
            if path not in domains:
                writes[DOMAINS_FILE] = yaml_text({**domains, path: description or path})
            writes.update(kb_missing(fs, path))
            if not writes:
                return {"domain": path, "commit": repo.head()}
            with repo.transaction(list(writes)):
                for name, content in writes.items():
                    fs.write(name, content)
                commit = repo.commit(f"Add domain {path}", actor.name, list(writes))
            self.rt.reindex()
            self.rt.state.audit(actor.name, "domain.add", path)
            return {"domain": path, "commit": commit}

    def page_template(self, type_name: str) -> dict[str, Any]:
        return self.rt.registry.page_type(type_name).model_dump()

    def next_adr(self, actor: Principal) -> dict[str, str]:
        require_role(actor, "writer")
        config = self.rt.settings
        with write_lock(config.state_dir, config.lock_timeout):
            roots = [config.wiki_root, *(config.state_dir / "worktrees").glob("*")]
            numbers = [
                int(match[1])
                for root in roots
                for page in read_pages(root)[0]
                if (match := re.fullmatch(r"adr-(\d{4})-.+", page.id))
            ]
            number = max(numbers, default=0) + 1
            if number > 9999:
                raise WikiError(
                    "E_ADR_EXHAUSTED",
                    "Свободных четырёхзначных номеров ADR не осталось.",
                    status=409,
                )
            return {"number": f"{number:04}"}
