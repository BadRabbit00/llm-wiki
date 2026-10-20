import re
from collections import Counter
from datetime import date, datetime
from typing import Any
from urllib.parse import urlsplit

from pydantic import ValidationError

from wikisvc.domain.errors import WikiError
from wikisvc.domain.ids import check_domain, check_id, page_path
from wikisvc.domain.markdown import (
    citations,
    content_hash,
    edges,
    parse,
    quote_too_short,
    render,
    sections,
    unparsed_citations,
)
from wikisvc.domain.models import SENSITIVITY_RANK, Edge, Frontmatter, LintIssue, Page, RelationRef
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


# doc: CLS-wikisvc-core.parse_page
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


VALID_FOR_KINDS = frozenset({"number", "api", "pitfall"})
ADOPTION = frozenset({"evaluating", "adopted", "avoid", "legacy", "unknown"})
FACT_BODY_MAX, DIGEST_MAX, URL_MAX = 1500, 800, 2048
CLAIM_MIN, CLAIM_MAX = 20, 200
VALID_FOR_CHARS = re.compile(r"[A-Za-z0-9_.:<>=!, -]{1,64}")
VALID_FOR_ATOM = re.compile(r"[A-Za-z0-9_.:-]+(?:\s*(?:>=|<=|==|!=|>|<)\s*[A-Za-z0-9_.-]+)?")
ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
# Checked by dedicated code below instead of the generic loop (it would report them twice).
DEDICATED_FIELDS = frozenset({("fact", "claim"), ("fact", "valid_for")})
# Required/default handling stays generic; the value itself is judged by the code below.
VALUE_CHECKED_IN_CODE = frozenset({("tech", "adoption"), ("tech", "homepage"), ("source", "url")})


def valid_for_ok(value: object) -> bool:
    """`condition (, condition)*`: `name op version` or a bare label, 1..64 safe characters."""
    return (
        isinstance(value, str)
        and VALID_FOR_CHARS.fullmatch(value) is not None
        and all(VALID_FOR_ATOM.fullmatch(part.strip()) for part in value.split(","))
    )


def http_url_ok(value: object) -> bool:
    """Only http(s) without userinfo and control characters, at most 2048 characters."""
    if not isinstance(value, str) or not value or len(value) > URL_MAX:
        return False
    if any(ord(char) < 33 or ord(char) == 127 for char in value):
        return False
    try:
        parts = urlsplit(value)
        return (
            parts.scheme in ("http", "https") and bool(parts.hostname) and "@" not in parts.netloc
        )
    except ValueError:
        return False


def relation_weight_issues(page: Page, registry: Registry) -> list[LintIssue]:
    """An extracted/inferred edge may not outweigh the base weight of its relation."""
    return [
        issue(
            "E_FRONTMATTER_INVALID",
            page.id,
            f"Вес w связи {rel} у автоматического ребра не выше базового ({registry.relations[rel].weight}).",
        )
        for rel, targets in page.frontmatter.relations.items()
        if rel in registry.relations
        for target in targets
        if isinstance(target, RelationRef)
        and target.origin != "manual"
        and target.w is not None
        and target.w > registry.relations[rel].weight
    ]


# doc: FMT-wikisvc-core.fact
def fact_issues(page: Page, extras: dict[str, Any], links: list[Edge]) -> list[LintIssue]:
    result = []
    claim = extras.get("claim")
    if (
        not isinstance(claim, str)
        or "\n" in claim
        or "\r" in claim
        or not CLAIM_MIN <= len(claim.strip()) <= CLAIM_MAX
    ):
        result.append(
            issue(
                "E_CLAIM_MISSING",
                page.id,
                f"У факта нужен claim: одна строка, {CLAIM_MIN}-{CLAIM_MAX} символов.",
            )
        )
    valid_for = extras.get("valid_for")
    if valid_for is None and extras.get("kind") in VALID_FOR_KINDS:
        result.append(
            issue("E_VALID_FOR_MISSING", page.id, "Для kind number/api/pitfall нужен valid_for.")
        )
    elif valid_for is not None and not valid_for_ok(valid_for):
        result.append(issue("E_FRONTMATTER_INVALID", page.id, "Недопустимое значение valid_for."))
    if len(page.body_md) > FACT_BODY_MAX:
        result.append(issue("W_FACT_LONG", page.id, "Факт длиннее 1500 символов: разбейте его."))
    if not any(edge.rel == "about" for edge in links):
        result.append(issue("W_FACT_NO_HUB", page.id, "Факт не привязан к хабу (about)."))
    return result


# doc: FMT-wikisvc-core.topic
def topic_issues(page: Page) -> list[LintIssue]:
    return [
        issue("W_DIGEST_LONG", page.id, "Digest длиннее 800 символов.")
        for section in sections(page.body_md)
        if section.heading == "Digest"
        and section.level == 2
        and len(section.text.partition("\n")[2].strip()) > DIGEST_MAX
    ]


# doc: FMT-wikisvc-core.tech
def tech_issues(page: Page, extras: dict[str, Any]) -> list[LintIssue]:
    result = []
    if extras.get("adoption") is not None and extras["adoption"] not in ADOPTION:
        result.append(issue("E_FRONTMATTER_INVALID", page.id, "Недопустимое значение adoption."))
    if extras.get("homepage") is not None and not http_url_ok(extras["homepage"]):
        result.append(issue("E_FRONTMATTER_INVALID", page.id, "Недопустимое значение homepage."))
    return result


# doc: FMT-wikisvc-core.question
def question_issues(page: Page, registry: Registry) -> list[LintIssue]:
    """`answered_by` answers with facts: every target carries the fact ID prefix."""
    prefix = registry.page_types["fact"].prefix + "-" if "fact" in registry.page_types else None
    return [
        issue("E_REL_TYPE_MISMATCH", page.id, "answered_by должен ссылаться на факты.")
        for target in page.frontmatter.relations.get("answered_by", [])
        if prefix and not (target if isinstance(target, str) else target.id).startswith(prefix)
    ]


# doc: FMT-wikisvc-core.source
def source_issues(page: Page, extras: dict[str, Any]) -> list[LintIssue]:
    if extras.get("url") is not None and not http_url_ok(extras["url"]):
        return [issue("E_FRONTMATTER_INVALID", page.id, "Недопустимое значение url.")]
    return []


def knowledge_issues(
    page: Page, extras: dict[str, Any], links: list[Edge], registry: Registry
) -> list[LintIssue]:
    """Local checks of the knowledge layer, dispatched by page type."""
    match page.frontmatter.type:
        case "fact":
            return fact_issues(page, extras, links)
        case "topic":
            return topic_issues(page)
        case "tech":
            return tech_issues(page, extras)
        case "question":
            return question_issues(page, registry)
        case "source":
            return source_issues(page, extras)
    return []


# doc: CLS-wikisvc-core.validate_page
def validate_page(
    page: Page, registry: Registry, entropy_threshold: float = 4.5
) -> list[LintIssue]:
    return validate_page_with_edges(page, registry, edges(page), entropy_threshold)


def validate_page_with_edges(
    page: Page, registry: Registry, links: list[Edge], entropy_threshold: float = 4.5
) -> list[LintIssue]:
    """`validate_page` for a caller that already computed `edges(page)` (computed once)."""
    fm = page.frontmatter
    result: list[LintIssue] = []
    try:
        definition = registry.page_type(fm.type)
        expected = page_path(
            registry, fm.type, page.id, (fm.model_extra or {}).get("parent"), fm.domain
        )
        if page.path and page.path != expected:
            result.append(issue("E_PATH_MISMATCH", page.id, f"Ожидаемый путь: {expected}"))
        if fm.domain is not None:
            check_domain(registry, fm.domain)
    except WikiError as exc:
        return [issue(exc.code, page.id, exc.message)]
    result.extend(
        issue("E_SCOPE_UNKNOWN", page.id, "Неизвестная область применения; см. /scopes.")
        for scope in fm.scopes
        if not registry.scope_known(scope)
    )
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
        if (fm.type, name) in DEDICATED_FIELDS:
            continue
        value = extras.get(name)
        if value is None and field.default is not None:
            value = field.default
        if value is None and field.required:
            result.append(
                issue(
                    "E_RULE_FIELDS" if fm.type == "rule" else "E_REQUIRED_FIELD",
                    page.id,
                    f"Обязательно поле {name}.",
                )
            )
        elif (
            value is not None
            and (fm.type, name) not in VALUE_CHECKED_IN_CODE
            and not valid_extra(value, field)
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
    result.extend(relation_weight_issues(page, registry))
    for edge in links:
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
    for _ in unparsed_citations(page.body_md):
        result.append(
            issue(
                "W_CITATION_UNPARSED",
                page.id,
                "Ссылка на источник не распознана: проверьте формат и кавычки.",
            )
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
    result.extend(knowledge_issues(page, extras, links, registry))
    if needs_source and not any(e.rel == "cites" for e in links):
        result.append(issue("W_NO_SOURCES", page.id, "Нет источников."))
    if len(fm.relations.get("related", [])) > 3:
        result.append(issue("W_TOO_MANY_RELATED", page.id, "Больше трёх слабых связей related."))
    if fm.summary == fm.title or len(fm.summary) < 20:
        result.append(issue("W_SUMMARY_WEAK", page.id, "Нужен содержательный summary."))
    if len(page.body_md) > 12000:
        result.append(issue("W_LONG_PAGE", page.id, "Разбейте страницу на несколько."))
    return result


def valid_extra(value: Any, field: ExtraField) -> bool:
    if value is None:
        # An absent value takes the field default, which must itself be valid.
        return field.default is not None and valid_extra(field.default, field)
    if field.type == "date":
        return (
            isinstance(value, date)
            and not isinstance(value, datetime)
            or (
                isinstance(value, str)
                and ISO_DATE.fullmatch(value) is not None
                and _is_calendar_date(value)
            )
        )
    if field.type == "dict":
        return (
            isinstance(value, dict)
            and len(value) >= field.min_items
            and (field.max_items is None or len(value) <= field.max_items)
            and all(
                isinstance(key, str)
                and isinstance(item, str)
                and (not field.item_enum or item in field.item_enum)
                and (not field.item_pattern or re.fullmatch(field.item_pattern, item) is not None)
                for key, item in value.items()
            )
        )
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


def _is_calendar_date(value: str) -> bool:
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def overlaps(left: list[str], right: list[str], registry: Registry | None = None) -> bool:
    if "*" in left or "*" in right or set(left) & set(right):
        return True
    return registry is not None and any(
        registry.scope_matches(a, b) or registry.scope_matches(b, a) for a in left for b in right
    )


def rule_scopes(page: Page) -> list[str]:
    """`applies_to` is the rule-level alias of the common `scopes` field."""
    applies_to = (page.frontmatter.model_extra or {}).get("applies_to")
    return applies_to if isinstance(applies_to, list) else page.frontmatter.scopes


# doc: CLS-wikisvc-core.validate_rule, FMT-wikisvc-core.rule
def validate_rule(page: Page, registry: Registry) -> list[LintIssue]:
    fm, result = page.frontmatter, []
    data = fm.model_extra or {}
    scopes = rule_scopes(page)
    if any(not registry.scope_known(scope) for scope in scopes):
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
        if all(
            quote_too_short(m[1])
            for m in re.finditer(
                r'\[@src-[a-z0-9-]+\s+(?:стр\.|гл\.)\s+\d+(?:-\d+)?\s+"([^"\n]+)"\]', page.body_md
            )
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
            links = edges(page)
            previous = (
                key,
                validate_page_with_edges(page, registry, links, self.entropy_threshold),
                links,
            )
            self.entries[page.id] = previous
        return previous[1], previous[2]


HUB_FACTS_MAX = 60


def _is_kb(page: Page) -> bool:
    return page.frontmatter.domain is not None


def _tech_scope_issues(page: Page, by_id: dict[str, Page], registry: Registry) -> list[LintIssue]:
    """`tech:<slug>` must name an existing `tech-<slug>` page (axis `from: tech-pages`)."""
    scopes = rule_scopes(page) if page.frontmatter.type == "rule" else page.frontmatter.scopes
    result = []
    for scope in scopes:
        axis, _, slug = scope.partition(":")
        definition = registry.scope_axes.get(axis)
        if definition is None or definition.source != "tech-pages":
            continue
        target = by_id.get(f"tech-{slug}")
        if target is None or target.frontmatter.type != "tech":
            result.append(
                issue(
                    "E_SCOPE_UNKNOWN", page.id, f"Область {scope} не соответствует tech-странице."
                )
            )
    return result


# doc: CLS-wikisvc-core.validate_set
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
    facts_per_hub: Counter[str] = Counter()
    for page in pages:
        if cache:
            local, links = cache.local(page, registry)
        else:
            links = edges(page)
            local = validate_page_with_edges(page, registry, links)
        result.extend(local)
        result.extend(_tech_scope_issues(page, by_id, registry))
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
            if edge.rel == "about" and page.frontmatter.type == "fact":
                facts_per_hub[edge.dst] += 1
            if (_is_kb(page) or _is_kb(target)) and (
                SENSITIVITY_RANK[target.frontmatter.sensitivity]
                > SENSITIVITY_RANK[page.frontmatter.sensitivity]
            ):
                result.append(
                    issue(
                        "E_SENSITIVITY_REF",
                        page.id,
                        f"Ссылка {edge.rel} ведёт на страницу с более высокой sensitivity.",
                        "Повысьте sensitivity этой страницы или уберите ссылку.",
                    )
                )
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
                        and overlaps(rule_scopes(page), rule_scopes(target), registry)
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
    for page in pages:
        if page.frontmatter.type == "topic":
            total = facts_per_hub[page.id]
            if total == 0:
                result.append(issue("W_HUB_EMPTY", page.id, "У хаба нет фактов."))
            elif total > HUB_FACTS_MAX:
                result.append(
                    issue("W_HUB_TOO_LARGE", page.id, f"У хаба {total} фактов: разделите тему.")
                )
    return result


# doc: CLS-wikisvc-core.require_valid
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
