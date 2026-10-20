import hashlib
import io
import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError
from ruamel.yaml.events import AliasEvent

from wikisvc.domain.errors import WikiError
from wikisvc.domain.models import Edge, Page


def load_yaml(text: str) -> Any:
    try:
        if any(isinstance(event, AliasEvent) for event in YAML(typ="safe").parse(text)):
            raise WikiError(
                "E_FRONTMATTER_INVALID", "YAML-алиасы не поддерживаются; укажите значения явно."
            )
        return YAML(typ="safe").load(text)
    except (YAMLError, ValueError, RecursionError) as exc:
        raise WikiError("E_FRONTMATTER_INVALID", "Некорректный YAML.") from exc


# doc: CLS-wikisvc-core.parse
def parse(text: str) -> tuple[dict[str, Any], str]:
    text = text.replace("\r\n", "\n").lstrip("\ufeff")
    match = re.match(r"\A---\s*\n(.*?)\n---[ \t]*(?:\n|$)", text, re.DOTALL)
    if not match:
        raise WikiError("E_FRONTMATTER_INVALID", "Ожидается YAML frontmatter между ---.")
    metadata = load_yaml(match[1])
    if not isinstance(metadata, dict) or any(not isinstance(key, str) for key in metadata):
        raise WikiError(
            "E_FRONTMATTER_INVALID", "Frontmatter должен быть словарём с текстовыми ключами."
        )
    return metadata, text[match.end() :].lstrip("\n")


# doc: CLS-wikisvc-core.render
def render(metadata: dict[str, Any], body: str) -> str:
    stream = io.StringIO()
    yaml = YAML()
    yaml.allow_unicode = True
    yaml.default_flow_style = False
    yaml.dump(metadata, stream)
    return "---\n" + stream.getvalue() + "---\n\n" + body.rstrip() + "\n"


# doc: CLS-wikisvc-core.content_hash
def content_hash(text: str) -> str:
    normalized = text.replace("\r\n", "\n").strip() + "\n"
    return "sha256:" + hashlib.sha256(normalized.encode()).hexdigest()


def without_code(text: str) -> str:
    """Mask code with spaces, preserving offsets for section edits."""
    lines = text.splitlines(keepends=True)
    marker, width = "", 0
    # CommonMark: indented code cannot interrupt a paragraph, and inside a list item it
    # starts only at the item's content indent + 4; `previous` and `item` track both.
    previous, item = "blank", -1
    output: list[str] = []
    for line in lines:
        content = line.rstrip("\n")
        stripped = content.lstrip(" \t")
        indent = len(content[: len(content) - len(stripped)].expandtabs(4))
        if not marker and stripped and indent < item and previous == "blank":
            item = -1
        base = max(item, 0)
        fence = re.match(r"(`{3,}|~{3,})(.*)$", stripped) if indent <= base + 3 else None
        bullet = re.match(r"([-+*]|\d{1,9}[.)])( +|$)", stripped) if indent < base + 4 else None
        hidden = bool(marker) or (bool(stripped) and indent >= base + 4 and previous != "text")
        if fence:
            hidden = True
            if not marker:
                marker, width = fence[1][0], len(fence[1])
            elif fence[1][0] == marker and len(fence[1]) >= width and not fence[2].strip():
                marker = ""
        elif bullet and not hidden:
            item = indent + len(bullet[1]) + (len(bullet[2]) if 0 < len(bullet[2]) <= 4 else 1)
        if not stripped:
            previous = "blank"
        elif hidden or re.match(r"#{1,6}(?:[ \t]|$)", stripped):
            previous = "block"
        else:
            previous = "text"
        output.append(re.sub(r"[^\n]", " ", line) if hidden else line)
    masked = "".join(output)
    # A code span never continues past a blank line; an unmatched backtick stays text.
    return re.sub(
        r"(`+)(?!`)((?:(?!\n[ \t]*\n)[\s\S])*?)(?<!`)\1(?!`)",
        lambda m: re.sub(r"[^\n]", " ", m[0]),
        masked,
    )


@dataclass(frozen=True)
class Section:
    heading: str
    level: int
    start: int
    body_start: int
    end: int
    text: str


def sections(body: str) -> list[Section]:
    matches = list(
        re.finditer(r"^ {0,3}(#{2,3})[ \t]+(.+?)[ \t]*#*[ \t]*$", without_code(body), re.MULTILINE)
    )
    result = []
    if not matches or matches[0].start() > 0:
        end = matches[0].start() if matches else len(body)
        result.append(Section("", 0, 0, 0, end, body[:end]))
    for pos, match in enumerate(matches):
        end = matches[pos + 1].start() if pos + 1 < len(matches) else len(body)
        result.append(
            Section(
                match[2].strip(),
                len(match[1]),
                match.start(),
                min(match.end() + 1, end),
                end,
                body[match.start() : end],
            )
        )
    return result


# doc: CLS-wikisvc-core.edges
def edges(page: Page) -> list[Edge]:
    result = {
        Edge(src=page.id, dst=dst, rel=rel, kind="frontmatter")
        for rel, targets in page.frontmatter.relations.items()
        for dst in targets
    }
    result.update(
        Edge(src=page.id, dst=dst, rel="cites", kind="citation") for dst in page.frontmatter.sources
    )
    clean = without_code(page.body_md)
    result.update(
        Edge(src=page.id, dst=m[1], rel="links_to", kind="wikilink")
        for m in re.finditer(r"\[\[([^\]|\n]+)(?:\|[^\]\n]*)?\]\]", clean)
    )
    result.update(
        Edge(src=page.id, dst=c.source, rel="cites", kind="citation") for c in citations(clean)
    )
    return sorted(result, key=lambda edge: (edge.src, edge.dst, edge.rel, edge.kind))


@dataclass(frozen=True)
class Citation:
    source: str
    unit: str | None = None
    start: int | None = None
    end: int | None = None
    quote: str | None = None


CITATION = re.compile(r'\[@(src-[a-z0-9-]+)(?:\s+(стр\.|гл\.)\s+(\d+)(?:-(\d+))?\s+"([^"\n]+)")?\]')


# doc: CLS-wikisvc-core.citations
def citations(text: str) -> list[Citation]:
    return [
        Citation(m[1], m[2], int(m[3]) if m[3] else None, int(m[4] or m[3]) if m[3] else None, m[5])
        for m in CITATION.finditer(without_code(text))
    ]


def unparsed_citations(text: str) -> list[str]:
    """Source references with a locator that `citations()` skips, e.g. a quote with an inner `"`.

    Such a reference yields neither a quote check nor a graph edge, so it must not stay silent.
    """
    clean = without_code(text)
    return [
        m[0]
        for m in re.finditer(r"\[@src-[^\s\]]*\s+(?:стр\.|гл\.)", clean)
        if not CITATION.match(clean, m.start())
    ]


def normalize_quote(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).casefold().replace("\u00ad", "")
    text = re.sub(r"(?<=\w)-\s*\n\s*(?=\w)", "", text)
    replacements: dict[str, str | int | None] = {
        "«": '"',
        "»": '"',
        "“": '"',
        "”": '"',
        "‘": "'",
        "’": "'",
        "—": "-",
        "–": "-",
        "‑": "-",
    }
    text = text.translate(str.maketrans(replacements))
    return " ".join(text.split())


def quote_too_short(quote: str) -> bool:
    # An empty normalized quote is a substring of any text, so it would "prove" nothing.
    return len(re.findall(r"\w+", normalize_quote(quote))) < 2
