from pathlib import Path

from pydantic import ValidationError

from wikisvc.domain.errors import WikiError
from wikisvc.domain.markdown import load_yaml
from wikisvc.domain.project_templates import ProjectTemplate
from wikisvc.domain.registry import Profile, Registry
from wikisvc.storage.safefs import SafeFS


def load_registry(root: Path) -> Registry:
    fs = SafeFS(root)
    registry = Registry.from_documents(
        [load_yaml(fs.read(path)) for path in fs.files("schema/page-types/*.yaml")],
        load_yaml(fs.read("schema/relations.yaml")),
        load_yaml(fs.read("schema/tags.yaml")) or [],
    )
    if fs.path("schema/scopes.yaml").exists():
        registry.scopes = load_yaml(fs.read("schema/scopes.yaml")) or []
    registry.profiles = {
        profile.id: profile
        for path in fs.files("schema/profiles/*.yaml")
        for profile in [Profile.model_validate(load_yaml(fs.read(path)))]
    }
    if fs.path("schema/synonyms.yaml").exists():
        registry.synonyms = load_yaml(fs.read("schema/synonyms.yaml")) or []
    for path in fs.files("schema/project-templates/*.yaml"):
        try:
            template = ProjectTemplate.model_validate(load_yaml(fs.read(path)))
        except ValidationError as exc:
            raise WikiError("E_TEMPLATE_INVALID", f"Невалидный шаблон проекта: {path}") from exc
        if template.id != Path(path).stem:
            raise WikiError("E_TEMPLATE_INVALID", "ID шаблона не совпадает с именем файла.")
        if template.profile not in registry.profiles:
            raise WikiError("E_TEMPLATE_INVALID", "Неизвестный профиль шаблона проекта.")
        if set(template.scopes) - set(registry.scopes):
            raise WikiError("E_TEMPLATE_INVALID", "Неизвестный scope шаблона проекта.")
        if any(block.profile not in registry.profiles for block in template.policy_blocks):
            raise WikiError("E_TEMPLATE_INVALID", "Неизвестный профиль блока политик шаблона.")
        registry.project_templates[template.id] = template
    return registry
