# doc: MOD-wikiagent.config
import os
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from wikisvc.domain.markdown import load_yaml


# doc: CFG-wikiagent.wikisvc.base_url, CFG-wikiagent.wikisvc.token_env, CFG-wikiagent.WIKIAGENT_TOKEN
class ServiceConfig(BaseModel):
    base_url: str = "http://127.0.0.1:8787"
    token_env: str = "WIKIAGENT_TOKEN"


# doc: CFG-wikiagent.models.planner, CFG-wikiagent.models.reviewer, CFG-wikiagent.models.chat
class ModelConfig(BaseModel):
    base_url: str
    model: str
    context: int = Field(default=32768, ge=4096)
    temperature: float = Field(default=0.2, ge=0, le=2)
    structured: Literal["json_schema", "json_object"] = "json_schema"
    token_env: str | None = None
    timeout_seconds: float = Field(default=120, gt=0)


# doc: CFG-wikiagent.limits.max_tool_steps, CFG-wikiagent.limits.chapter_chunk_tokens
# doc: CFG-wikiagent.limits.retries, CFG-wikiagent.limits.state_tokens
class Limits(BaseModel):
    max_tool_steps: int = Field(default=25, ge=1, le=100)
    chapter_chunk_tokens: int = Field(default=8000, ge=100, le=16000)
    retries: int = Field(default=3, ge=1, le=3)
    state_tokens: int = Field(default=1500, ge=100, le=1500)


# doc: CFG-wikiagent.heal.enabled, CFG-wikiagent.heal.idle_minutes, CFG-wikiagent.heal.windows
# doc: CFG-wikiagent.heal.max_findings_per_run, CFG-wikiagent.heal.max_model_calls_per_run
# doc: CFG-wikiagent.heal.max_model_calls_per_day, CFG-wikiagent.heal.confidence_threshold
# doc: CFG-wikiagent.heal.full_sweep_days, CFG-wikiagent.heal.k_candidates
# doc: CFG-wikiagent.heal.candidate_stale_days
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

    @field_validator("windows")
    @classmethod
    def valid_windows(cls, values: list[str]) -> list[str]:
        if any(
            not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d-(?:[01]\d|2[0-3]):[0-5]\d", value)
            for value in values
        ):
            raise ValueError("windows use HH:MM-HH:MM in server local time")
        return values


# doc: CFG-wikiagent.docs_audit.enabled, CFG-wikiagent.docs_audit.max_findings_per_run
# doc: CFG-wikiagent.docs_audit.max_model_calls_per_run, CFG-wikiagent.docs_audit.max_model_calls_per_day
# doc: CFG-wikiagent.docs_audit.confidence_threshold, CFG-wikiagent.docs_audit.max_files
# doc: CFG-wikiagent.docs_audit.max_total_bytes
class DocsAuditConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    max_findings_per_run: int = Field(default=20, ge=1, le=100)
    max_model_calls_per_run: int = Field(default=100, ge=1)
    max_model_calls_per_day: int = Field(default=1000, ge=1)
    confidence_threshold: float = Field(default=0.7, ge=0, le=1)
    max_files: int = Field(default=200, ge=1, le=200)
    max_total_bytes: int = Field(default=26214400, ge=1, le=26214400)


# doc: CFG-wikiagent.max_upload_mb, CFG-wikiagent.secret_entropy_threshold, CFG-wikiagent.state_dir
# doc: CFG-wikiagent.bind_host, CFG-wikiagent.bind_port
# doc: CFG-wikiagent.MAX_UPLOAD_MB, CFG-wikiagent.SECRET_ENTROPY_THRESHOLD, CFG-wikiagent.WIKIAGENT_STATE_DIR
class AgentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    wikisvc: ServiceConfig = Field(default_factory=ServiceConfig)
    models: dict[str, ModelConfig]
    limits: Limits = Field(default_factory=Limits)
    heal: HealConfig = Field(default_factory=HealConfig)
    docs_audit: DocsAuditConfig = Field(default_factory=DocsAuditConfig)
    max_upload_mb: int = Field(
        default_factory=lambda: int(os.environ.get("MAX_UPLOAD_MB", "25")),
        ge=1,
        le=1024,
        validate_default=True,
    )
    secret_entropy_threshold: float = Field(
        default_factory=lambda: float(os.environ.get("SECRET_ENTROPY_THRESHOLD", "4.5")),
        gt=0,
        validate_default=True,
    )
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


# doc: CFG-wikiagent.WIKIAGENT_CONFIG, FMT-wikiagent.config
def load_config(path: Path | None = None) -> AgentConfig:
    return AgentConfig.model_validate(
        load_yaml((path or Path(os.environ.get("WIKIAGENT_CONFIG", "wikiagent.yaml"))).read_text())
    )
