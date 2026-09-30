import re
from pathlib import PurePosixPath

from wikisvc.domain.errors import WikiError
from wikisvc.domain.registry import Registry


def check_id(value: str) -> str:
    if len(value) > 80 or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", value):
        raise WikiError(
            "E_ID_INVALID",
            "ID должен содержать строчные латинские буквы, цифры и дефисы (до 80 символов).",
        )
    return value


def page_path(registry: Registry, type_name: str, page_id: str, parent: str | None = None) -> str:
    check_id(page_id)
    definition = registry.page_type(type_name)
    if not page_id.startswith(definition.prefix + "-"):
        raise WikiError("E_ID_INVALID", f"Для {type_name} нужен префикс {definition.prefix}-.")
    slug = page_id[len(definition.prefix) + 1 :]
    parent_slug = ""
    if type_name == "app-doc":
        if not parent:
            raise WikiError("E_REQUIRED_FIELD", "app-doc требует parent.")
        check_id(parent)
        if not parent.startswith("app-") or not page_id.startswith("appdoc-" + parent[4:] + "-"):
            raise WikiError("E_ID_INVALID", "ID app-doc должен начинаться с appdoc-{parent_slug}-.")
        parent_slug = parent[4:]
    if type_name == "adr" and not re.fullmatch(r"\d{4}-.+", slug):
        raise WikiError("E_ID_INVALID", "ADR требует ID adr-NNNN-название (латиница).")
    path = "wiki/" + definition.path_template.format(slug=slug, parent_slug=parent_slug)
    if ".." in PurePosixPath(path).parts or PurePosixPath(path).is_absolute() or "\\" in path:
        raise WikiError("E_PATH_MISMATCH", "Небезопасный шаблон пути.")
    return path
