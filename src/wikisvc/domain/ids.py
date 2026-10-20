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


def check_page_id(registry: Registry, value: str) -> str:
    """A page ID is `<type prefix>-<slug>`; without a known prefix no page path can exist."""
    check_id(value)
    if not any(value.startswith(t.prefix + "-") for t in registry.page_types.values()):
        raise WikiError(
            "E_ID_INVALID", "ID страницы должен начинаться с префикса типа: <префикс>-<название>."
        )
    return value


DOMAIN_PATH = re.compile(r"[a-z0-9-]+(?:/[a-z0-9-]+)*")


def check_domain(registry: Registry, value: str | None) -> str:
    """The domain must be exactly a path listed in `schema/domains.yaml`."""
    if value is None or not DOMAIN_PATH.fullmatch(value) or value not in registry.domains:
        raise WikiError(
            "E_DOMAIN_UNKNOWN",
            "Домен не из schema/domains.yaml.",
            "Возьмите домен из списка доменов; новый добавляет администратор.",
        )
    return value


# doc: CLS-wikisvc-core.page_path
def page_path(
    registry: Registry,
    type_name: str,
    page_id: str,
    parent: str | None = None,
    domain: str | None = None,
) -> str:
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
    domain_path = ""
    if "{domain}" in definition.path_template:
        if domain is None:
            raise WikiError("E_REQUIRED_FIELD", f"{type_name} требует поле domain.")
        domain_path = check_domain(registry, domain)
    path = "wiki/" + definition.path_template.format(
        slug=slug, parent_slug=parent_slug, domain=domain_path
    )
    if (
        ".." in PurePosixPath(path).parts
        or PurePosixPath(path).is_absolute()
        or "\\" in path
        or "\0" in path
    ):
        raise WikiError("E_PATH_MISMATCH", "Небезопасный шаблон пути.")
    return path
