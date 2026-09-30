from pathlib import Path

from wikisvc.index.indexer import read_pages
from wikisvc.storage.safefs import SafeFS
from wikisvc.storage.state_db import now


def generate(root: Path, message: str) -> None:
    fs = SafeFS(root)
    pages, _ = read_pages(root)
    index = (
        "# Индекс вики\n\n"
        + "\n".join(
            f"- [[{page.id}|{page.frontmatter.title}]] — {page.frontmatter.summary}"
            for page in sorted(pages, key=lambda p: (p.frontmatter.type, p.id))
        )
        + "\n"
    )
    fs.write("wiki/index.md", index)
    log = fs.read("wiki/log.md") if fs.path("wiki/log.md").exists() else "# Журнал вики\n"
    fs.write("wiki/log.md", log.rstrip() + f"\n\n- {now()} — {message}\n")
