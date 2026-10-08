"""Local session issuance and operator-owned group mappings; no OIDC or network access."""

import hashlib
import re
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator
from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from wikisvc.config import Settings
from wikisvc.domain.errors import WikiError
from wikisvc.domain.models import Principal, Role, Sensitivity
from wikisvc.services.auth import Auth
from wikisvc.storage.state_db import StateDB, now


class Grant(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Role = "reader"
    clearance: Sensitivity = "public"


class RoleMap(BaseModel):
    model_config = ConfigDict(extra="forbid")
    default: Grant = Field(default_factory=Grant)
    groups: dict[str, Grant]

    @model_validator(mode="after")
    def deny_by_default(self) -> "RoleMap":
        if self.default != Grant():
            raise ValueError("Unmapped users must remain reader/public")
        return self

    def resolve(self, groups: list[str]) -> Grant:
        matches = [self.groups[group] for group in groups if group in self.groups]
        if not matches:
            return self.default
        roles: list[Role] = ["reader", "writer", "reviewer", "admin"]
        levels: list[Sensitivity] = ["public", "internal", "restricted"]
        return Grant(
            role=max((grant.role for grant in matches), key=roles.index),
            clearance=max((grant.clearance for grant in matches), key=levels.index),
        )


def load_roles(path: Path) -> RoleMap:
    try:
        with path.open(encoding="utf-8") as stream:
            return RoleMap.model_validate(YAML(typ="safe").load(stream))
    except (OSError, YAMLError, ValueError) as exc:
        raise ValueError("ROLES_FILE must contain a valid operator-owned roles mapping") from exc


def token_name(state: StateDB, token: str) -> str:
    """Resolve a previously authenticated credential, independently of display_name."""
    rows = state.rows(
        "SELECT name FROM tokens WHERE token_hash=?",
        (hashlib.sha256(token.encode()).hexdigest(),),
    )
    if not rows:
        raise WikiError("E_UNAUTHORIZED", "Нужен действующий Bearer-токен.", status=401)
    return str(rows[0]["name"])


def safe_name(username: str, subject: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_.-]+", "-", username).strip("._-")[:64]
    return value or "user-" + re.sub(r"[^A-Za-z0-9_.-]", "-", subject[:8])


class SessionRequest(BaseModel):
    subject: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.@-]{0,127}$", max_length=128)
    username: str = Field(default="", max_length=1024)
    groups: list[str] = Field(default_factory=list, max_length=1000)


class SessionResponse(BaseModel):
    token: str
    expires_at: str
    actor: Principal


class Sessions:
    def __init__(self, config: Settings, auth: Auth) -> None:
        self.config, self.auth = config, auth
        self.roles = load_roles(config.roles_file) if config.session_issuer_token_name else None
        self._name_lock = threading.Lock()
        self._last_name = 0

    def create(self, request: SessionRequest, issuer: Principal) -> SessionResponse:
        if self.roles is None:
            raise WikiError("E_NOT_FOUND", "Выпуск сессий выключен.", status=404)
        grant = self.roles.resolve(request.groups)
        display_name = safe_name(request.username, request.subject)
        expires_at = (
            datetime.now(UTC) + timedelta(hours=self.config.session_ttl_hours)
        ).isoformat()
        with self._name_lock:
            # Nanosecond Unix timestamps also distinguish two logins in the same second.
            self._last_name = max(time.time_ns(), self._last_name + 1)
            prefix = re.sub(r"[^A-Za-z0-9_.-]", "-", request.subject[:8])
            name = f"sso-{prefix}-{self._last_name}"
            token = self.auth.create(
                name,
                grant.role,
                grant.clearance,
                person=request.subject,
                kind="human",
                expires_at=expires_at,
                display_name=display_name,
            )
        actor = Principal(
            name=display_name,
            person=request.subject,
            kind="human",
            role=grant.role,
            clearance=grant.clearance,
        )
        self.auth.state.audit(issuer.name, "token.session.create", request.subject)
        with self.auth.state.connect() as db:
            db.execute(
                "INSERT INTO people(person,display_name,updated_at) VALUES (?,?,?) "
                "ON CONFLICT(person) DO UPDATE SET display_name=excluded.display_name,updated_at=excluded.updated_at",
                (request.subject, display_name, now()),
            )
        return SessionResponse(token=token, expires_at=expires_at, actor=actor)
