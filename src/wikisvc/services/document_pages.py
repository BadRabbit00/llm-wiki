"""Document parsing helpers imported only inside the limited extraction subprocess."""

import posixpath
import re
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from xml.etree import ElementTree


class HTMLText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.ignore = 0
        self.pre = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style"):
            self.ignore += 1
        if tag in ("p", "div", "h1", "h2", "h3", "li", "br"):
            self.parts.append("\n\n")
        if tag == "pre":
            self.pre += 1
            self.parts.append("\n```\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style"):
            self.ignore = max(0, self.ignore - 1)
        if tag in ("p", "div", "h1", "h2", "h3", "li"):
            self.parts.append("\n\n")
        if tag == "pre":
            self.pre = max(0, self.pre - 1)
            self.parts.append("\n```\n")

    def handle_data(self, data: str) -> None:
        if not self.ignore:
            self.parts.append(data)


def xml(data: bytes) -> ElementTree.Element:
    if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        raise ValueError("XML entities forbidden")
    return ElementTree.fromstring(data)


def epub(file: Path) -> list[dict[str, Any]]:
    with zipfile.ZipFile(file) as archive:
        infos = archive.infolist()
        if (
            len(infos) > 20000
            or sum(i.file_size for i in infos) > file.stat().st_size * 10
            or any(i.file_size > 20_000_000 for i in infos)
        ):
            raise ValueError("EPUB expansion limit")
        container = xml(archive.read("META-INF/container.xml"))
        rootfile = next(
            e.attrib["full-path"] for e in container.iter() if e.tag.endswith("rootfile")
        )
        package = xml(archive.read(rootfile))
        items = {
            e.attrib["id"]: e.attrib
            for e in package.iter()
            if e.tag.endswith("}item") or e.tag == "item"
        }
        ids = [
            e.attrib["idref"]
            for e in package.iter()
            if e.tag.endswith("itemref") and e.attrib.get("linear", "yes") != "no"
        ]
        pages = []
        for n, key in enumerate(ids, 1):
            href = items[key]["href"].split("#")[0]
            path = posixpath.normpath(posixpath.join(posixpath.dirname(rootfile), href))
            if path.startswith(("../", "/")) or ":" in path:
                raise ValueError("Unsafe EPUB path")
            parser = HTMLText()
            parser.feed(archive.read(path).decode("utf-8-sig"))
            text = "".join(parser.parts).strip()
            title = next(
                (line.strip() for line in text.splitlines() if line.strip()), f"Chapter {n}"
            )[:200]
            pages.append({"n": n, "text": text, "title": title})
        return pages


def batch(file: Path, start: int, count: int) -> dict[str, Any]:
    outline = []
    if file.suffix.lower() == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(str(file))
        total = len(reader.pages)
        pages = [
            {"n": n + 1, "text": reader.pages[n].extract_text() or ""}
            for n in range(start - 1, min(total, start - 1 + count))
        ]

        def bookmarks(values: list[Any]) -> None:
            for value in values:
                if isinstance(value, list):
                    bookmarks(value)
                else:
                    number = reader.get_destination_page_number(value)
                    if number is not None:
                        outline.append({"title": str(value.title), "page_from": number + 1})

        bookmarks(reader.outline)
    else:
        if file.suffix.lower() == ".epub":
            all_pages = epub(file)
            outline = [{"title": p["title"], "page_from": p["n"]} for p in all_pages]
        else:
            if file.suffix.lower() == ".docx":
                from docx import Document

                text = "\n\n".join(p.text for p in Document(str(file)).paragraphs)
            else:
                text = file.read_text(encoding="utf-8-sig")
            parts = (
                re.split(r"\f", text)
                if "\f" in text
                else [text[n : n + 4000] for n in range(0, len(text), 4000)]
            )
            all_pages = [{"n": n, "text": part} for n, part in enumerate(parts, 1)]
        total = len(all_pages)
        pages = all_pages[start - 1 : start - 1 + count]
    return {"total": total, "pages": pages, "outline": outline}
