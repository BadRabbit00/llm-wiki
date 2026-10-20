"""Environment-based service configuration."""

from pathlib import Path
from typing import Literal, Self

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# doc: CLS-wikisvc.Settings
# doc: CFG-wikisvc.WIKI_ROOT, CFG-wikisvc.STATE_DIR, CFG-wikisvc.INDEX_DIR, CFG-wikisvc.BIND_HOST
# doc: CFG-wikisvc.CORS_ORIGINS, CFG-wikisvc.ANONYMOUS_ACCESS, CFG-wikisvc.ANONYMOUS_NAME
# doc: CFG-wikisvc.ANONYMOUS_ROLE, CFG-wikisvc.ANONYMOUS_CLEARANCE
# doc: CFG-wikisvc.SESSION_ISSUER_TOKEN_NAME, CFG-wikisvc.SESSION_TTL_HOURS, CFG-wikisvc.ROLES_FILE
# doc: CFG-wikisvc.MCP_HTTP_ENABLED, CFG-wikisvc.MCP_HTTP_PATH, CFG-wikisvc.MCP_PROFILE
# doc: CFG-wikisvc.WIKIAGENT_STATE_DIR, CFG-wikisvc.BIND_PORT, CFG-wikisvc.MAX_LIBRARY_UPLOAD_MB
# doc: CFG-wikisvc.EXTRACT_JOB_MAX_CHARS, CFG-wikisvc.EXTRACT_JOB_TIMEOUT
# doc: CFG-wikisvc.OUTLINE_FALLBACK_PAGES, CFG-wikisvc.MAX_UPLOAD_MB, CFG-wikisvc.PROPOSAL_TTL_DAYS
# doc: CFG-wikisvc.CONTEXT_BUDGET_DEFAULT, CFG-wikisvc.CHARS_PER_TOKEN
# doc: CFG-wikisvc.POLICY_CATEGORY_ORDER, CFG-wikisvc.STATUS_BOOST, CFG-wikisvc.RELATION_PRIORITY
# doc: CFG-wikisvc.ALLOWED_RAW_EXT, CFG-wikisvc.RATE_LIMIT_PER_MIN, CFG-wikisvc.LOG_LEVEL
# doc: CFG-wikisvc.EXTRACT_TIMEOUT_SECONDS, CFG-wikisvc.EXTRACT_MEMORY_MB
# doc: CFG-wikisvc.EXTRACT_MAX_CHARS, CFG-wikisvc.SECRET_ENTROPY_THRESHOLD, CFG-wikisvc.LOCK_TIMEOUT
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    wiki_root: Path
    state_dir: Path
    index_dir: Path
    bind_host: str = "127.0.0.1"
    cors_origins: str = ""
    anonymous_access: bool = False
    anonymous_name: str = Field(default="anonymous", pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
    anonymous_role: Literal["reader", "writer"] = "writer"
    anonymous_clearance: Literal["public", "internal"] = "internal"
    session_issuer_token_name: str = ""
    session_ttl_hours: int = Field(default=12, ge=1)
    roles_file: Path = Path("/etc/llm-wiki/roles.yaml")
    mcp_http_enabled: bool = False
    mcp_http_path: str = Field(default="/mcp", pattern=r"^/")
    mcp_profile: str = "coding"
    wikiagent_state_dir: Path | None = None
    bind_port: int = Field(default=8787, ge=1, le=65535)
    max_library_upload_mb: int = Field(default=200, ge=1, le=1024)
    extract_job_max_chars: int = Field(default=50_000_000, ge=1000, le=200_000_000)
    extract_job_timeout: int = Field(default=600, ge=1, le=7200)
    outline_fallback_pages: int = Field(default=15, ge=1, le=100)
    max_upload_mb: int = Field(default=25, ge=1, le=1024)
    proposal_ttl_days: int = Field(default=14, ge=1)
    context_budget_default: int = Field(default=12000, ge=1, le=60000)
    chars_per_token: float = Field(default=2.5, ge=1, le=10)
    policy_category_order: str = (
        "code-style,architecture,logging,errors,security,testing,stack,git,build-ci,docs,process"
    )
    status_boost: str = "verified=1.2,draft=1.0,outdated=0.5"
    relation_priority: str = "governed_by,depends_on,uses,reads,writes,automates"
    allowed_raw_ext: str = "pdf,epub,docx,xlsx,md,txt,csv,json,yaml,yml,png,jpg,jpeg"
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
        self.roles_file = self.roles_file.resolve()
        if self.roles_file.is_relative_to(self.wiki_root):
            raise ValueError("ROLES_FILE must be outside WIKI_ROOT")
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
