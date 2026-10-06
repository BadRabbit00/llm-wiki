import re
from collections import Counter
from typing import Any

from pydantic import ValidationError

from wikisvc.domain.errors import WikiError
from wikisvc.domain.ids import check_id, page_path
from wikisvc.domain.markdown import citations, content_hash, edges, parse, render, sections
from wikisvc.domain.models import Edge, Frontmatter, LintIssue, Page
from wikisvc.domain.registry import ExtraField, Registry
from wikisvc.domain.secrets import secret_kinds


def issue(
    code: str, page: str | None, message: str, hint: str = "Исправьте страницу по /schema."
) -> LintIssue:
    return LintIssue(
        code=code,
        severity="error"
        if code.startswith("E_")
        else "info"
        if code == "W_MUST_WITHOUT_ENFORCER"
        else "warning",
        page=page,
        message=message,
        hint=hint,
    )


def parse_page(text: str, path: str = "") -> Page:
    fm, body = parse(text)
    if fm.get("type") == "rule" and isinstance(fm.get("summary"), str) and len(fm["summary"]) > 160:
        raise WikiError("E_SUMMARY_TOO_LONG", "Тезис правила должен быть не длиннее 160 символов.")
    try:
        return Page(
            frontmatter=Frontmatter.model_validate(fm),
            body_md=body,
            path=path,
            version=content_hash(text),
        )
    except ValidationError as exc:
        missing = any(error["type"] == "missing" for error in exc.errors())
        raise WikiError(
            "E_REQUIRED_FIELD" if missing else "E_FRONTMATTER_INVALID",
            "Поля frontmatter не соответствуют схеме.",
            details=[
                {"field": ".".join(map(str, e["loc"])), "message": e["msg"]} for e in exc.errors()
            ],
        ) from exc


def validate_page(
    page: Page, registry: Registry, entropy_threshold: float = 4.5
) -> list[LintIssue]:
    fm = page.frontmatter
    result: list[LintIssue] = []
    try:
        definition = registry.page_type(fm.type)
        expected = page_path(registry, fm.type, page.id, (fm.model_extra or {}).get("parent"))
        if page.path and page.path != expected:
            result.append(issue("E_PATH_MISMATCH", page.id, f"Ожидаемый путь: {expected}"))
    except WikiError as exc:
        return [issue(exc.code, page.id, exc.message)]
    present = {s.heading for s in sections(page.body_md) if s.level == 2}
    if len(fm.summary) > definition.summary_max:
        result.append(
            issue(
                "E_SUMMARY_TOO_LONG", page.id, f"Тезис: не более {definition.summary_max} символов."
            )
        )
    for heading in definition.required_sections:
        if heading not in present:
            result.append(issue("E_SECTION_MISSING", page.id, f"Отсутствует раздел H2: {heading}"))
    extras = fm.model_extra or {}
    for name, field in definition.extra_fields.items():
        value = extras.get(name)
        if value is None and field.required:
            result.append(
                issue(
                    "E_RULE_FIELDS" if fm.type == "rule" else "E_REQUIRED_FIELD",
                    page.id,
                    f"Обязательно поле {name}.",
                )
            )
        elif value is not None and not valid_extra(value, field):
            result.append(issue("E_FRONTMATTER_INVALID", page.id, f"Недопустимое значение {name}."))
    for name in extras.keys() - definition.extra_fields.keys():
        result.append(issue("E_FRONTMATTER_INVALID", page.id, f"Неизвестное поле: {name}."))
    for tag in fm.tags:
        if tag not in registry.tags:
            result.append(issue("E_TAG_UNKNOWN", page.id, f"Неизвестный тег: {tag}."))
    for rel in fm.relations:
        if rel not in registry.relations:
            result.append(
                issue("E_REL_UNKNOWN", page.id, f"Неизвестная или обратная связь: {rel}.")
            )
        elif rel not in definition.allowed_relations:
            result.append(
                issue("E_REL_TYPE_MISMATCH", page.id, f"Связь {rel} недопустима для {fm.type}.")
            )
    for edge in edges(page):
        try:
            check_id(edge.dst)
        except WikiError:
            result.append(issue("E_ID_INVALID", page.id, "Некорректный ID в ссылке."))
        if edge.rel == "cites" and not edge.dst.startswith("src-"):
            result.append(issue("E_REL_TYPE_MISMATCH", page.id, "Источники должны иметь ID src-*."))
    for citation in citations(page.body_md):
        if citation.quote and len(citation.quote.split()) > 30:
            result.append(
                issue("E_QUOTE_TOO_LONG", page.id, "Цитата должна содержать не более 30 слов.")
            )
    safe_metadata = fm.model_dump(
        mode="json", exclude={"created", "updated", "verified_by", "verified_at"}
    )
    safe_metadata.pop("raw_sha256", None)
    if secret_kinds(render(safe_metadata, page.body_md), entropy_threshold):
        result.append(
            issue(
                "E_SECRET_DETECTED",
                page.id,
                "Обнаружен возможный секрет.",
                "Замените секрет ссылкой на хранилище или ${VAR}.",
            )
        )
    needs_source = definition.sources_required and fm.type != "source"
    if fm.type == "rule":
        result.extend(validate_rule(page, registry))
        needs_source = extras.get("origin") in ("book", "article")
    if needs_source and not any(e.rel == "cites" for e in edges(page)):
        result.append(issue("W_NO_SOURCES", page.id, "Нет источников."))
    if len(fm.relations.get("related", [])) > 3:
        result.append(issue("W_TOO_MANY_RELATED", page.id, "Больше трёх слабых связей related."))
    if fm.summary == fm.title or len(fm.summary) < 20:
        result.append(issue("W_SUMMARY_WEAK", page.id, "Нужен содержательный summary."))
    if len(page.body_md) > 12000:
        result.append(issue("W_LONG_PAGE", page.id, "Разбейте страницу на несколько."))
    return result


def valid_extra(value: Any, field: ExtraField) -> bool:
    if field.type == "str":
        return (
            isinstance(value, str)
            and (not field.enum or value in field.enum)
            and (not field.pattern or re.fullmatch(field.pattern, value) is not None)
            and (field.max_length is None or len(value) <= field.max_length)
        )
    if field.type == "int":
        return (
            type(value) is int
            and (field.min is None or value >= field.min)
            and (field.max is None or value <= field.max)
        )
    return (
        isinstance(value, list)
        and len(value) >= field.min_items
        and (field.max_items is None or len(value) <= field.max_items)
        and all(
            isinstance(item, str)
            and (not field.item_enum or item in field.item_enum)
            and (not field.item_pattern or re.fullmatch(field.item_pattern, item) is not None)
            for item in value
        )
    )


def overlaps(left: list[str], right: list[str]) -> bool:
    return "*" in left or "*" in right or bool(set(left) & set(right))


def validate_rule(page: Page, registry: Registry) -> list[LintIssue]:
    fm, result = page.frontmatter, []
    data = fm.model_extra or {}
    scopes = data.get("applies_to", [])
    if isinstance(scopes, list) and any(
        scope != "*" and scope not in registry.scopes for scope in scopes
    ):
        result.append(
            issue("E_SCOPE_UNKNOWN", page.id, "Неизвестная область применения; см. /scopes.")
        )
    if data.get("lifecycle") == "active" and not fm.verified_by:
        result.append(
            issue(
                "E_RULE_ACTIVE_NOT_VERIFIED",
                page.id,
                "Активное правило должно быть подтверждено человеком.",
            )
        )
    if data.get("lifecycle") == "candidate" and (
        fm.status != "draft" or data.get("level") not in ("idea", "should")
    ):
        result.append(
            issue(
                "E_RULE_FIELDS", page.id, "Кандидат должен иметь status=draft и level=idea|should."
            )
        )
    if data.get("level") == "must" and not data.get("owner"):
        result.append(
            issue("E_MUST_NEEDS_OWNER", page.id, "Для обязательного правила нужен владелец.")
        )
    if data.get("level") == "must" and not fm.sources:
        result.append(
            issue("E_RULE_FIELDS", page.id, "Обязательное правило требует источник решения.")
        )
    if data.get("lifecycle") == "deprecated" and not data.get("deprecated_reason"):
        result.append(issue("E_RULE_FIELDS", page.id, "Нужна причина снятия правила."))
    if data.get("origin") in ("book", "article"):
        if not fm.sources:
            result.append(
                issue("E_RULE_FIELDS", page.id, "Правило из книги или статьи требует sources.")
            )
        if not re.search(
            r'\[@src-[a-z0-9-]+\s+(?:стр\.|гл\.)\s+\d+(?:-\d+)?\s+"[^"\n]+"\]', page.body_md
        ):
            result.append(
                issue("W_NO_CITATION", page.id, "Нужна короткая цитата со страницей или главой.")
            )
    if len(fm.aliases) < 2:
        result.append(issue("W_FEW_ALIASES", page.id, "Добавьте русский и английский алиасы."))
    if data.get("level") == "must" and (
        not data.get("enforced_by") or data.get("enforced_by") == ["none"]
    ):
        result.append(
            issue(
                "W_MUST_WITHOUT_ENFORCER",
                page.id,
                "Укажите проверку линтером или CI, если она возможна.",
            )
        )
    return result


class ValidationCache:
    """Reuse local checks for unchanged pages; always recheck cross-page constraints."""

    def __init__(self, entropy_threshold: float = 4.5) -> None:
        self.entropy_threshold = entropy_threshold
        self.registry: Registry | None = None
        self.entries: dict[str, tuple[tuple[str, str, str], list[LintIssue], list[Edge]]] = {}

    def local(self, page: Page, registry: Registry) -> tuple[list[LintIssue], list[Edge]]:
        if registry != self.registry:
            self.entries.clear()
            self.registry = registry
        key = (page.frontmatter.model_dump_json(), page.body_md, page.path)
        previous = self.entries.get(page.id)
        if previous is None or previous[0] != key:
            previous = (key, validate_page(page, registry, self.entropy_threshold), edges(page))
            self.entries[page.id] = previous
        return previous[1], previous[2]


def validate_set(
    pages: list[Page], registry: Registry, cache: ValidationCache | None = None
) -> list[LintIssue]:
    by_id = {page.id: page for page in pages}
    if cache:
        cache.entries = {key: value for key, value in cache.entries.items() if key in by_id}
    result = [
        issue("E_ID_DUPLICATE", key, "ID встречается несколько раз.")
        for key, count in Counter(p.id for p in pages).items()
        if count > 1
    ]
    for page in pages:
        local, links = (
            cache.local(page, registry) if cache else (validate_page(page, registry), edges(page))
        )
        result.extend(local)
        for edge in links:
            if edge.dst not in by_id:
                result.append(
                    issue(
                        "E_LINK_UNRESOLVED",
                        page.id,
                        f"Ссылка {edge.rel} ведёт на отсутствующий ID {edge.dst}.",
                        "Найдите ID через /search или создайте страницу в этом предложении.",
                    )
                )
                continue
            target = by_id[edge.dst]
            if page.frontmatter.type == "rule" and target.frontmatter.type == "rule":
                source_extra, target_extra = (
                    page.frontmatter.model_extra or {},
                    target.frontmatter.model_extra or {},
                )
                if source_extra.get("lifecycle") == "active":
                    if target_extra.get("lifecycle") == "deprecated" and edge.rel in (
                        "depends_on",
                        "refines",
                        "links_to",
                        "related",
                    ):
                        result.append(
                            issue(
                                "W_DEPENDS_ON_DEPRECATED",
                                page.id,
                                f"Правило ссылается на снятое {target.id}.",
                            )
                        )
                    if (
                        edge.rel == "conflicts_with"
                        and target_extra.get("lifecycle") == "active"
                        and overlaps(
                            source_extra.get("applies_to", []), target_extra.get("applies_to", [])
                        )
                    ):
                        result.append(
                            issue(
                                "W_RULE_CONFLICT",
                                page.id,
                                f"Пересекающееся активное правило {target.id} помечено как конфликтующее.",
                            )
                        )
            rule = registry.relations.get(edge.rel)
            if rule and (
                (rule.from_types and page.frontmatter.type not in rule.from_types)
                or (rule.to and target.frontmatter.type not in rule.to)
                or (rule.same_type and target.frontmatter.type != page.frontmatter.type)
            ):
                result.append(
                    issue(
                        "E_REL_TYPE_MISMATCH", page.id, f"Недопустимая пара типов для {edge.rel}."
                    )
                )
        for field, expected_type in (("parent", "app"), ("owner", "role")):
            value: Any = (page.frontmatter.model_extra or {}).get(field)
            if (
                field == "owner"
                and page.frontmatter.type == "rule"
                and isinstance(value, str)
                and not value.startswith("role-")
            ):
                continue
            if value and (value not in by_id or by_id[value].frontmatter.type != expected_type):
                result.append(
                    issue(
                        "E_LINK_UNRESOLVED",
                        page.id,
                        f"{field} должен ссылаться на {expected_type}.",
                    )
                )
    return result


def require_valid(issues: list[LintIssue]) -> None:
    errors = [value for value in issues if value.severity == "error"]
    if errors:
        raise WikiError(
            errors[0].code, errors[0].message, errors[0].hint, [e.model_dump() for e in errors]
        )


def check_version(expected: str | None, actual: str | None) -> None:
    if actual is not None and expected != actual:
        raise WikiError(
            "E_VERSION_CONFLICT",
            "Версия страницы изменилась.",
            "Прочитайте страницу заново и укажите её version в base_version.",
            status=409,
        )
