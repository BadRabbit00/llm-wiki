import logging
from pathlib import Path

from pydantic import ValidationError

from wikisvc.domain.errors import WikiError
from wikisvc.domain.ids import DOMAIN_PATH
from wikisvc.domain.markdown import load_yaml
from wikisvc.domain.project_templates import ProjectTemplate
from wikisvc.domain.registry import PageType, Profile, Registry, Relation, ScopeAxis
from wikisvc.storage.safefs import SafeFS

logger = logging.getLogger(__name__)


def _load_project_template(fs: SafeFS, path: str, registry: Registry) -> ProjectTemplate:
    try:
        data = load_yaml(fs.read(path))
    except (WikiError, OSError, UnicodeError) as exc:
        raise WikiError("E_TEMPLATE_INVALID", "Не удалось прочитать YAML шаблона проекта.") from exc
    try:
        template = ProjectTemplate.model_validate(data)
    except ValidationError as exc:
        raise WikiError("E_TEMPLATE_INVALID", "Невалидная структура шаблона проекта.") from exc
    if template.id != Path(path).stem:
        raise WikiError("E_TEMPLATE_INVALID", "ID шаблона не совпадает с именем файла.")
    if template.profile not in registry.profiles:
        raise WikiError("E_TEMPLATE_INVALID", "Неизвестный профиль шаблона проекта.")
    if set(template.scopes) - set(registry.scopes):
        raise WikiError("E_TEMPLATE_INVALID", "Неизвестный scope шаблона проекта.")
    if any(block.profile not in registry.profiles for block in template.policy_blocks):
        raise WikiError("E_TEMPLATE_INVALID", "Неизвестный профиль блока политик шаблона.")
    return template


def _schema_invalid(file: str, reason: str) -> WikiError:
    return WikiError("E_SCHEMA_INVALID", f"{file}: {reason}")


def _read_schema_yaml(fs: SafeFS, path: str) -> object:
    """Parse one schema file; any read or YAML failure names the file (fail closed)."""
    try:
        data: object = load_yaml(fs.read(path))
    except (WikiError, OSError, UnicodeError) as exc:
        raise _schema_invalid(path, "файл не читается или не является YAML") from exc
    return data


# doc: FMT-wikisvc-core.domains
def load_domains(fs: SafeFS) -> dict[str, str]:
    """Fail closed: a malformed line refuses the whole schema instead of being skipped."""
    path = "schema/domains.yaml"
    if not fs.path(path).exists():
        return {}
    data = _read_schema_yaml(fs, path)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise _schema_invalid(path, "ожидается словарь путь -> описание")
    result: dict[str, str] = {}
    for key, description in data.items():
        if not isinstance(key, str) or not DOMAIN_PATH.fullmatch(key):
            raise _schema_invalid(path, "ключ не является путём домена")
        if not isinstance(description, str) or not description.strip():
            raise _schema_invalid(path, f"у домена {key} нет описания-строки")
        result[key] = description
    for key in result:
        parent = key.rpartition("/")[0]
        if parent and parent not in result:
            raise _schema_invalid(path, f"у домена {key} нет родителя {parent}")
    return result


def _load_scopes(fs: SafeFS) -> tuple[list[str], dict[str, ScopeAxis]]:
    """`axes` + `values`, or the old plain list (axes are then the value prefixes)."""
    path = "schema/scopes.yaml"
    if not fs.path(path).exists():
        return [], {}
    data = _read_schema_yaml(fs, path) or []
    raw_values: object
    raw_axes: object = {}
    if isinstance(data, list):
        raw_values = data
    elif isinstance(data, dict):
        raw_values, raw_axes = data.get("values") or [], data.get("axes") or {}
    else:
        raise _schema_invalid(path, "ожидается список или словарь axes/values")
    if not isinstance(raw_values, list) or not all(isinstance(v, str) for v in raw_values):
        raise _schema_invalid(path, "values должен быть списком строк")
    values = [value for value in raw_values if isinstance(value, str)]
    if not isinstance(raw_axes, dict):
        raise _schema_invalid(path, "axes должен быть словарём осей")
    axes: dict[str, ScopeAxis] = {}
    for name, axis in raw_axes.items():
        if not isinstance(name, str) or not isinstance(axis, dict):
            raise _schema_invalid(path, "axes должен быть словарём осей")
        try:
            axes[name] = ScopeAxis.model_validate(axis)
        except ValidationError as exc:
            raise _schema_invalid(path, f"некорректное описание оси {name}") from exc
    for value in values:
        axes.setdefault(value.partition(":")[0], ScopeAxis())
    return values, axes


def _load_page_types(fs: SafeFS) -> list[dict[str, object]]:
    result = []
    for path in fs.files("schema/page-types/*.yaml"):
        data = _read_schema_yaml(fs, path)
        try:
            PageType.model_validate(data)
        except ValidationError as exc:
            raise _schema_invalid(path, "некорректное описание типа страницы") from exc
        if isinstance(data, dict):
            result.append(data)
    return result


def _load_relations(fs: SafeFS) -> dict[str, object]:
    path = "schema/relations.yaml"
    data = _read_schema_yaml(fs, path)
    if not isinstance(data, dict) or not all(isinstance(name, str) for name in data):
        raise _schema_invalid(path, "ожидается словарь связей")
    for name, relation in data.items():
        try:
            Relation.model_validate(relation)
        except ValidationError as exc:
            raise _schema_invalid(path, f"некорректная связь {name}") from exc
    return dict(data)


# doc: CLS-wikisvc-core.load_registry, FMT-wikisvc-core.scopes
def load_registry(root: Path) -> Registry:
    fs = SafeFS(root)
    tags = _read_schema_yaml(fs, "schema/tags.yaml") or []
    if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
        raise _schema_invalid("schema/tags.yaml", "ожидается список строк")
    registry = Registry.from_documents(_load_page_types(fs), _load_relations(fs), tags)
    registry.scopes, registry.scope_axes = _load_scopes(fs)
    registry.domains = load_domains(fs)
    registry.profiles = {
        profile.id: profile
        for path in fs.files("schema/profiles/*.yaml")
        for profile in [Profile.model_validate(load_yaml(fs.read(path)))]
    }
    if fs.path("schema/synonyms.yaml").exists():
        registry.synonyms = load_yaml(fs.read("schema/synonyms.yaml")) or []
    for path in fs.files("schema/project-templates/*.yaml"):
        try:
            template = _load_project_template(fs, path, registry)
        except WikiError as exc:
            template_id = Path(path).stem
            registry.invalid_project_templates[template_id] = exc.message
            logger.warning("Шаблон проекта %r в карантине: %s", template_id, exc.message)
            continue
        registry.project_templates[template.id] = template
    return registry
