from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from wikisvc.domain.errors import WikiError
from wikisvc.domain.models import Principal
from wikisvc.index.indexer import read_pages
from wikisvc.services.auth import require_role
from wikisvc.storage.lock import write_lock
from wikisvc.storage.safefs import SafeFS

if TYPE_CHECKING:
    from wikisvc.services.runtime import Runtime


class Schema:
    def __init__(self, runtime: Runtime) -> None:
        self.rt = runtime

    def instructions(self) -> dict[str, str]:
        fs = SafeFS(self.rt.settings.wiki_root)
        return {
            "instructions": "\n\n".join(
                fs.read(path) for path in ["AGENTS.md", *fs.files("schema/workflows/*.md")]
            )
        }

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
