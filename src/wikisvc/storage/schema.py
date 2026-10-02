from pathlib import Path

from wikisvc.domain.markdown import load_yaml
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
    return registry
