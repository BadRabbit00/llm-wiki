"""Environment-based service configuration."""

from pathlib import Path
from typing import Literal, Self

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    wiki_root: Path
    state_dir: Path
    index_dir: Path
    bind_host: str = "127.0.0.1"
    bind_port: int = Field(default=8787, ge=1, le=65535)
    max_upload_mb: int = Field(default=25, ge=1, le=1024)
    proposal_ttl_days: int = Field(default=14, ge=1)
    context_budget_default: int = Field(default=12000, ge=1, le=60000)
    embeddings_enabled: bool = False
    embeddings_provider: str = "none"
    status_boost: str = "verified=1.2,draft=1.0,outdated=0.5"
    relation_priority: str = "governed_by,depends_on,uses,reads,writes,automates"
    allowed_raw_ext: str = "pdf,docx,xlsx,md,txt,csv,json,yaml,yml,png,jpg,jpeg"
    rate_limit_per_min: int = Field(default=0, ge=0)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    extract_timeout_seconds: int = Field(default=15, ge=1, le=300)
    extract_memory_mb: int = Field(default=512, ge=128, le=4096)
    extract_max_chars: int = Field(default=2_000_000, ge=1000, le=10_000_000)
    secret_entropy_threshold: float = Field(default=4.5, gt=0)
    lock_timeout: float = Field(default=30.0, gt=0)

    @model_validator(mode="after")
    def validate_directories(self) -> Self:
        self.wiki_root = self.wiki_root.resolve()
        self.state_dir = self.state_dir.resolve()
        self.index_dir = self.index_dir.resolve()
        for directory in (self.state_dir, self.index_dir):
            if directory.is_relative_to(self.wiki_root):
                raise ValueError("STATE_DIR and INDEX_DIR must be outside WIKI_ROOT")
        if self.state_dir == self.index_dir:
            raise ValueError("STATE_DIR and INDEX_DIR must be separate directories")
        self.boosts()
        return self

    def boosts(self) -> dict[str, float]:
        result = {
            key: float(value) for key, value in (x.split("=") for x in self.status_boost.split(","))
        }
        if set(result) != {"verified", "draft", "outdated"} or any(
            not 0 <= value <= 100 for value in result.values()
        ):
            raise ValueError("STATUS_BOOST requires verified, draft, outdated with finite weights")
        return result
