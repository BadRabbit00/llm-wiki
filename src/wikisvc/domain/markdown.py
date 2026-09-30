import hashlib
import io
import re
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


def render(metadata: dict[str, Any], body: str) -> str:
    stream = io.StringIO()
    yaml = YAML()
    yaml.allow_unicode = True
    yaml.default_flow_style = False
    yaml.dump(metadata, stream)
    return "---\n" + stream.getvalue() + "---\n\n" + body.rstrip() + "\n"


def content_hash(text: str) -> str:
    normalized = text.replace("\r\n", "\n").strip() + "\n"
    return "sha256:" + hashlib.sha256(normalized.encode()).hexdigest()


def without_code(text: str) -> str:
    """Mask code with spaces, preserving offsets for section edits."""
    lines = text.splitlines(keepends=True)
    marker, width = "", 0
    output: list[str] = []
    for line in lines:
        fence = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line.rstrip("\n"))
        hidden = bool(marker) or line.startswith(("    ", "\t"))
        if fence:
            hidden = True
            if not marker:
                marker, width = fence[1][0], len(fence[1])
            elif fence[1][0] == marker and len(fence[1]) >= width and not fence[2].strip():
                marker = ""
        output.append(re.sub(r"[^\n]", " ", line) if hidden else line)
    masked = "".join(output)
    return re.sub(
        r"(`+)(?!`)([\s\S]*?)(?<!`)\1(?!`)", lambda m: re.sub(r"[^\n]", " ", m[0]), masked
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
        Edge(src=page.id, dst=m[1], rel="cites", kind="citation")
        for m in re.finditer(r"\[@([^\]\n]+)\]", clean)
    )
    return sorted(result, key=lambda edge: (edge.src, edge.dst, edge.rel, edge.kind))
