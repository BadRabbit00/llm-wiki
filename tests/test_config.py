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


@pytest.mark.parametrize(
    "value",
    ["draft=nan", "draft=-1,verified=1,outdated=1", "verified=1,draft=101,outdated=1", "bad"],
)
def test_invalid_weights(tmp_path: Path, value: str) -> None:
    with pytest.raises(ValidationError):
        Settings(
            wiki_root=tmp_path / "wiki",
            state_dir=tmp_path / "state",
            index_dir=tmp_path / "index",
            status_boost=value,
        )


def test_nan_weight_is_refused_when_every_key_is_present(tmp_path: Path) -> None:
    def settings(status_boost: str) -> Settings:
        return Settings(
            wiki_root=tmp_path / "wiki",
            state_dir=tmp_path / "state",
            index_dir=tmp_path / "index",
            status_boost=status_boost,
        )

    # Same keys and the same valid neighbours: only the NaN weight separates the two.
    assert settings("verified=1,draft=0.5,outdated=1").boosts() == {
        "verified": 1.0,
        "draft": 0.5,
        "outdated": 1.0,
    }
    with pytest.raises(ValidationError, match="finite weights"):
        settings("verified=1,draft=nan,outdated=1")
