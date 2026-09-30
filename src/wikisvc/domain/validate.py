import re
from collections import Counter
from typing import Any

from pydantic import ValidationError

from wikisvc.domain.errors import WikiError
from wikisvc.domain.ids import check_id, page_path
from wikisvc.domain.markdown import content_hash, edges, parse, render, sections
from wikisvc.domain.models import Frontmatter, LintIssue, Page
from wikisvc.domain.registry import Registry
from wikisvc.domain.secrets import secret_kinds


def issue(
    code: str, page: str | None, message: str, hint: str = "Исправьте страницу по /schema."
) -> LintIssue:
    return LintIssue(
        code=code,
        severity="error" if code.startswith("E_") else "warning",
        page=page,
        message=message,
        hint=hint,
    )


def parse_page(text: str, path: str = "") -> Page:
    fm, body = parse(text)
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
    for heading in definition.required_sections:
        if heading not in present:
            result.append(issue("E_SECTION_MISSING", page.id, f"Отсутствует раздел H2: {heading}"))
    extras = fm.model_extra or {}
    for name, field in definition.extra_fields.items():
        value = extras.get(name)
        if value is None and field.required:
            result.append(issue("E_REQUIRED_FIELD", page.id, f"Обязательно поле {name}."))
        elif value is not None and (
            not isinstance(value, str)
            or (field.enum and value not in field.enum)
            or (field.pattern and not re.fullmatch(field.pattern, value))
        ):
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
    if fm.type != "source" and not any(e.rel == "cites" for e in edges(page)):
        result.append(issue("W_NO_SOURCES", page.id, "Нет источников."))
    if len(fm.relations.get("related", [])) > 3:
        result.append(issue("W_TOO_MANY_RELATED", page.id, "Больше трёх слабых связей related."))
    if fm.summary == fm.title or len(fm.summary) < 20:
        result.append(issue("W_SUMMARY_WEAK", page.id, "Нужен содержательный summary."))
    if len(page.body_md) > 12000:
        result.append(issue("W_LONG_PAGE", page.id, "Разбейте страницу на несколько."))
    return result


def validate_set(pages: list[Page], registry: Registry) -> list[LintIssue]:
    by_id = {page.id: page for page in pages}
    result = [
        issue("E_ID_DUPLICATE", key, "ID встречается несколько раз.")
        for key, count in Counter(p.id for p in pages).items()
        if count > 1
    ]
    for page in pages:
        result.extend(validate_page(page, registry))
        for edge in edges(page):
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
