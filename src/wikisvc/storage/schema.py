from pathlib import Path

from wikisvc.domain.markdown import load_yaml
from wikisvc.domain.registry import Registry
from wikisvc.storage.safefs import SafeFS


def load_registry(root: Path) -> Registry:
    fs = SafeFS(root)
    return Registry.from_documents(
        [load_yaml(fs.read(path)) for path in fs.files("schema/page-types/*.yaml")],
        load_yaml(fs.read("schema/relations.yaml")),
        load_yaml(fs.read("schema/tags.yaml")) or [],
    )
