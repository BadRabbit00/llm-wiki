from itertools import groupby
from pathlib import Path

from wikisvc.domain.models import Page
from wikisvc.storage.safefs import SafeFS
from wikisvc.storage.state_db import now


def render_index(pages: list[Page]) -> str:
    groups = []
    for kind, group in groupby(
        sorted(pages, key=lambda p: (p.frontmatter.type, p.id)), key=lambda p: p.frontmatter.type
    ):
        groups.append(
            f"## {kind}\n\n"
            + "\n".join(
                f"- [[{page.id}|{page.frontmatter.title}]] — {page.frontmatter.summary}"
                for page in group
            )
        )
    return "# Индекс вики\n\n" + "\n\n".join(groups) + "\n"


def generate(root: Path, message: str, author: str, pages: list[Page]) -> None:
    fs = SafeFS(root)
    fs.write("wiki/index.md", render_index(pages))
    log = fs.read("wiki/log.md") if fs.path("wiki/log.md").exists() else "# Журнал вики\n"
    fs.write("wiki/log.md", log.rstrip() + f"\n\n- [accept] {now()} author={author} — {message}\n")
