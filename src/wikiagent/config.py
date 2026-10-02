import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from wikisvc.domain.markdown import load_yaml


class ServiceConfig(BaseModel):
    base_url: str = "http://127.0.0.1:8787"
    token_env: str = "WIKIAGENT_TOKEN"


class ModelConfig(BaseModel):
    base_url: str
    model: str
    context: int = Field(default=32768, ge=4096)
    temperature: float = Field(default=0.2, ge=0, le=2)
    structured: Literal["json_schema", "json_object"] = "json_schema"
    token_env: str | None = None
    timeout_seconds: float = Field(default=120, gt=0)


class Limits(BaseModel):
    max_tool_steps: int = Field(default=25, ge=1, le=100)
    chapter_chunk_tokens: int = Field(default=8000, ge=100, le=16000)
    retries: int = Field(default=3, ge=1, le=3)
    state_tokens: int = Field(default=1500, ge=100, le=1500)


class HealConfig(BaseModel):
    enabled: bool = True
    idle_minutes: int = Field(default=15, ge=0)
    windows: list[str] = Field(default_factory=lambda: ["01:00-06:00"])
    max_findings_per_run: int = Field(default=20, ge=1, le=100)
    max_model_calls_per_run: int = Field(default=100, ge=1)
    max_model_calls_per_day: int = Field(default=2000, ge=1)
    confidence_threshold: float = Field(default=0.7, ge=0, le=1)
    full_sweep_days: int = Field(default=7, ge=1)
    k_candidates: int = Field(default=8, ge=1, le=20)
    candidate_stale_days: int = Field(default=30, ge=1)


class AgentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    wikisvc: ServiceConfig = Field(default_factory=ServiceConfig)
    models: dict[str, ModelConfig]
    limits: Limits = Field(default_factory=Limits)
    heal: HealConfig = Field(default_factory=HealConfig)
    state_dir: Path = Field(
        default_factory=lambda: Path(os.environ.get("WIKIAGENT_STATE_DIR", ".wikiagent"))
    )
    bind_host: str = "127.0.0.1"
    bind_port: int = Field(default=8788, ge=1, le=65535)

    @model_validator(mode="after")
    def roles(self) -> "AgentConfig":
        if set(self.models) != {"planner", "reviewer", "chat"}:
            raise ValueError("models must define planner, reviewer and chat")
        return self


def load_config(path: Path | None = None) -> AgentConfig:
    return AgentConfig.model_validate(
        load_yaml((path or Path(os.environ.get("WIKIAGENT_CONFIG", "wikiagent.yaml"))).read_text())
    )
