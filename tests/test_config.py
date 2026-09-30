from pathlib import Path

import pytest
from pydantic import ValidationError

from wikisvc.config import Settings


def test_directories_and_weights(tmp_path: Path) -> None:
    config = Settings(
        wiki_root=tmp_path / "wiki", state_dir=tmp_path / "state", index_dir=tmp_path / "index"
    )
    assert config.boosts()["verified"] == 1.2
    with pytest.raises(ValidationError):
        Settings(wiki_root=tmp_path, state_dir=tmp_path / "state", index_dir=tmp_path / "index")
    with pytest.raises(ValidationError):
        Settings(
            wiki_root=tmp_path / "wiki",
            state_dir=tmp_path / "state",
            index_dir=tmp_path / "state",
        )


@pytest.mark.parametrize("value", ["draft=nan", "draft=-1,verified=1,outdated=1", "bad"])
def test_invalid_weights(tmp_path: Path, value: str) -> None:
    with pytest.raises(ValidationError):
        Settings(
            wiki_root=tmp_path / "wiki",
            state_dir=tmp_path / "state",
            index_dir=tmp_path / "index",
            status_boost=value,
        )
