from pathlib import Path

import pytest
from conftest import make_page
from hypothesis import given
from hypothesis import strategies as st

from wikisvc.domain.errors import WikiError
from wikisvc.domain.ids import check_id, page_path
from wikisvc.domain.markdown import (
    Citation,
    citations,
    content_hash,
    edges,
    parse,
    render,
    sections,
    without_code,
)
from wikisvc.domain.registry import Registry
from wikisvc.domain.secrets import secret_kinds
from wikisvc.domain.validate import (
    check_version,
    parse_page,
    require_valid,
    validate_page,
    validate_set,
)
from wikisvc.services.initialize import initialize
from wikisvc.storage.safefs import SafeFS


def test_links_and_sections_ignore_code(registry: Registry) -> None:
    page = make_page(registry)
    page.body_md = """## Определение
[[sys-bank|банк]] [@src-bank]
`[[sys-inline]]` ``some ` [[sys-inline-two]]``
```python
## Fake
[[sys-fenced]] [@src-fenced]
```
~~~
[[sys-tilde]]
~~~
    [[sys-indented]]
### Детали
text
"""
    assert {edge.dst for edge in edges(page)} == {"sys-bank", "src-bank"}
    assert [s.heading for s in sections(page.body_md)] == ["Определение", "Детали"]
    assert len(without_code(page.body_md)) == len(page.body_md)
    assert content_hash("abc\r\n") == content_hash("abc\n")


def test_unpaired_backtick_does_not_hide_next_paragraphs(registry: Registry) -> None:
    page = make_page(registry)
    page.body_md = """Вступление с `незакрытой кавычкой.

## Определение

См. [[sys-after-tick]] и [@src-after-tick стр. 3 "Цитата после абзаца"].

Текст с `code`.
"""
    assert {edge.dst for edge in edges(page)} == {"sys-after-tick", "src-after-tick"}
    assert [s.heading for s in sections(page.body_md)] == ["", "Определение"]
    assert citations(page.body_md) == [
        Citation("src-after-tick", "стр.", 3, 3, "Цитата после абзаца")
    ]
    problems = validate_set([page], registry)
    assert "E_SECTION_MISSING" not in {problem.code for problem in problems}
    assert sorted(p.message for p in problems if p.code == "E_LINK_UNRESOLVED") == [
        "Ссылка cites ведёт на отсутствующий ID src-after-tick.",
        "Ссылка links_to ведёт на отсутствующий ID sys-after-tick.",
    ]
    assert len(without_code(page.body_md)) == len(page.body_md)


def test_indented_lines_are_code_only_outside_paragraphs_and_lists(registry: Registry) -> None:
    page = make_page(registry)
    page.body_md = """## Определение

- Пункт списка
    продолжение со ссылкой [[sys-list-tail]]

1. Шаг
    ```text
    ## Не раздел [[sys-fenced-in-item]]
    ```

    Абзац шага [@src-step]

        [[sys-code-in-item]]

Абзац
    ленивое продолжение [[sys-lazy]]

    [[sys-real-code]]
### Детали

text
"""
    assert {edge.dst for edge in edges(page)} == {"sys-list-tail", "src-step", "sys-lazy"}
    assert [s.heading for s in sections(page.body_md)] == ["Определение", "Детали"]
    assert [c.source for c in citations(page.body_md)] == ["src-step"]
    problems = validate_set([page], registry)
    assert "E_SECTION_MISSING" not in {problem.code for problem in problems}
    assert sorted(p.message for p in problems if p.code == "E_LINK_UNRESOLVED") == [
        "Ссылка cites ведёт на отсутствующий ID src-step.",
        "Ссылка links_to ведёт на отсутствующий ID sys-lazy.",
        "Ссылка links_to ведёт на отсутствующий ID sys-list-tail.",
    ]


@pytest.mark.parametrize(
    "text", ["", "abc", "---\n[]\n---\nx", "---\na: [\n---\nx", "---\n1: value\n---\n"]
)
def test_invalid_frontmatter(text: str) -> None:
    with pytest.raises(WikiError) as error:
        parse(text)
    assert error.value.code == "E_FRONTMATTER_INVALID"


@given(st.text())
def test_parse_arbitrary_text(text: str) -> None:
    try:
        parse(text)
    except WikiError:
        pass


@given(st.text(alphabet=st.characters(blacklist_categories=("Cs",)), max_size=500))
def test_roundtrip(body: str) -> None:
    metadata = {"id": "term-test", "tags": ["тест"], "relations": {"related": ["term-other"]}}
    parsed, result = parse(render(metadata, body))
    assert parsed == metadata
    assert result.strip() == body.replace("\r\n", "\n").strip()


def test_all_paths(registry: Registry) -> None:
    assert len(registry.page_types) == 17
    for kind, definition in registry.page_types.items():
        page_id = definition.prefix + "-example"
        extra = {}
        if kind == "app-doc":
            page_id, extra = "appdoc-example-notes", {"parent": "app-example"}
        if kind == "adr":
            page_id = "adr-0001-example"
        if "{domain}" in definition.path_template:
            extra = {"domain": "db"}
        actual = page_path(registry, kind, page_id, **extra)
        assert actual.startswith("wiki/") and actual.endswith(".md")
    assert (
        page_path(registry, "app-doc", "appdoc-example-notes", "app-example")
        == "wiki/apps/example/example-notes.md"
    )
    assert page_path(registry, "system", "sys-bank") == "wiki/systems/bank.md"


@pytest.mark.parametrize("value", ["../bad", "ABC", "a--b", "/etc/passwd", "a" * 81, "", "bad_id"])
def test_bad_id(value: str) -> None:
    with pytest.raises(WikiError, match="ID"):
        check_id(value)


def test_validation_error_codes(registry: Registry) -> None:
    cases = [
        ("type", "unknown", "E_TYPE_UNKNOWN"),
        ("id", "sys-wrong", "E_ID_INVALID"),
        ("tags", ["bad"], "E_TAG_UNKNOWN"),
        ("relations", {"unknown": ["term-other"]}, "E_REL_UNKNOWN"),
        ("relations", {"automates": ["term-other"]}, "E_REL_TYPE_MISMATCH"),
    ]
    for field, value, code in cases:
        page = make_page(registry)
        setattr(page.frontmatter, field, value)
        assert code in {i.code for i in validate_page(page, registry)}
    page = make_page(registry)
    page.path = "wiki/wrong.md"
    page.body_md = "password=abcdefgh1234"
    assert {"E_PATH_MISMATCH", "E_SECTION_MISSING", "E_SECRET_DETECTED"} <= {
        i.code for i in validate_page(page, registry)
    }
    with pytest.raises(WikiError) as error:
        parse_page("---\nid: term-test\n---\n")
    assert error.value.code == "E_REQUIRED_FIELD"
    with pytest.raises(WikiError) as error:
        parse_page(
            render({**make_page(registry).frontmatter.model_dump(), "summary": "short"}, "body")
        )
    assert error.value.code == "E_FRONTMATTER_INVALID"
    page = make_page(registry)
    page.body_md += "\n[[term-missing]]"
    issues = validate_set([page, page], registry)
    assert {"E_ID_DUPLICATE", "E_LINK_UNRESOLVED"} <= {i.code for i in issues}
    with pytest.raises(WikiError):
        require_valid(issues)
    require_valid([])
    with pytest.raises(WikiError) as error:
        check_version(None, "sha256:one")
    assert error.value.code == "E_VERSION_CONFLICT"
    check_version("same", "same")
    check_version(None, None)


def test_extra_fields_and_relation_types(registry: Registry) -> None:
    app = make_page(registry, "app-example", "app")
    assert "E_REQUIRED_FIELD" in {i.code for i in validate_page(app, registry)}
    app.frontmatter.__pydantic_extra__ = {"app_status": "bad", "unknown": "x"}
    assert "E_FRONTMATTER_INVALID" in {i.code for i in validate_page(app, registry)}
    app.frontmatter.__pydantic_extra__ = {"app_status": "idea", "owner": "role-missing"}
    term = make_page(registry)
    app.frontmatter.relations = {"automates": [term.id]}
    assert {"E_REL_TYPE_MISMATCH", "E_LINK_UNRESOLVED"} <= {
        i.code for i in validate_set([app, term], registry)
    }
    with pytest.raises(WikiError):
        page_path(registry, "app-doc", "appdoc-other", "app-example")
    with pytest.raises(WikiError):
        page_path(registry, "app-doc", "appdoc-other")
    with pytest.raises(WikiError):
        page_path(registry, "adr", "adr-example")


@pytest.mark.parametrize(
    "secret",
    [
        "-----BEGIN RSA PRIVATE KEY-----",
        "AKIA" + "A1" * 8,
        "ghp_" + "a1" * 20,
        "xoxb-" + "12ab" * 8,
        "eyJabcdefghijk.abcdefghijkl.1234567890abc",
        "password: example123",
        "api_key = example123",
        "aB3zP9qW4eR7tY2uI6oL8kJ5hG0fD1sA",
    ],
)
def test_secrets(secret: str) -> None:
    assert secret_kinds(secret)


@pytest.mark.parametrize(
    "safe",
    [
        "password: <секрет>",
        "token=${TOKEN}",
        "Пароль хранится в Vault.",
        "token: abc",
        "a9c26d14f8b0375ea6d190cb8f257e4a10bc9d3e7f6028a145c3b9e827af60d5",
        "a" * 80,
        "Описание конфигурации и технических ограничений.",
    ],
)
def test_not_secrets(safe: str) -> None:
    assert not secret_kinds(safe)


def test_safe_filesystem_and_init(tmp_path: Path) -> None:
    root = tmp_path / "wiki"
    initialize(root)
    fs = SafeFS(root)
    assert fs.read("CLAUDE.md") == fs.read("AGENTS.md")
    assert len(fs.files("schema/page-types/*.yaml")) == 17
    for path in ["../outside", "/etc/passwd", "a/../../bad", "a\\bad", "bad\0"]:
        with pytest.raises(WikiError):
            fs.path(path)
    (root / "escape").symlink_to(tmp_path)
    with pytest.raises(WikiError):
        fs.write("escape/outside", "bad")
    fs.write("inbox/test.txt", "test")
    assert fs.read("inbox/test.txt") == "test"
    fs.remove("inbox/test.txt")
    with pytest.raises(WikiError):
        initialize(root)
