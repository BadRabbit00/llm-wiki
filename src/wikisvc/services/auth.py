import hashlib
import hmac
import re
import secrets
import sqlite3
import time
from datetime import UTC, datetime
from typing import Literal

from wikisvc.domain.errors import WikiError
from wikisvc.domain.models import Principal, Role, Sensitivity
from wikisvc.storage.state_db import StateDB, now


def require_role(actor: Principal, role: Role) -> None:
    roles = ["reader", "writer", "reviewer", "admin"]
    if roles.index(actor.role) < roles.index(role):
        raise WikiError("E_FORBIDDEN", "Недостаточно прав.", status=403)


def can_read(actor: Principal, sensitivity: str) -> bool:
    levels = ["public", "internal", "restricted"]
    return levels.index(sensitivity) <= levels.index(actor.clearance)


def require_human(actor: Principal) -> None:
    require_role(actor, "reviewer")
    if actor.kind != "human":
        raise WikiError(
            "E_HUMAN_REQUIRED", "Решение должен подтвердить человек своим токеном.", status=403
        )


class Auth:
    def __init__(self, state: StateDB, rate_limit: int = 0) -> None:
        self.state = state
        self.rate_limit = rate_limit

    def create(
        self,
        name: str,
        role: Role,
        clearance: Sensitivity,
        person: str | None = None,
        kind: Literal["agent", "human"] = "agent",
        expires_at: str | None = None,
    ) -> str:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", name):
            raise WikiError(
                "E_TOKEN_NAME", "Имя токена: латиница, цифры, точка, дефис, подчёркивание (1–64)."
            )
        Principal(name=name, role=role, clearance=clearance, person=person, kind=kind)
        if person and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.@-]{0,127}", person):
            raise WikiError("E_TOKEN_PERSON", "person: стабильный идентификатор до 128 символов.")
        if expires_at:
            try:
                expiry = datetime.fromisoformat(expires_at)
                if expiry.tzinfo is None:
                    raise ValueError
                expires_at = expiry.astimezone(UTC).isoformat()
            except ValueError as exc:
                raise WikiError(
                    "E_REQUEST_INVALID", "expires_at: дата ISO 8601 с часовым поясом."
                ) from exc
        token = secrets.token_urlsafe(32)
        try:
            with self.state.connect() as db:
                db.execute(
                    "INSERT INTO tokens (token_hash,name,role,clearance,created_at,person,kind,expires_at) VALUES (?,?,?,?,?,?,?,?)",
                    (
                        hashlib.sha256(token.encode()).hexdigest(),
                        name,
                        role,
                        clearance,
                        now(),
                        person,
                        kind,
                        expires_at,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise WikiError("E_TOKEN_EXISTS", "Имя токена уже используется.", status=409) from exc
        self.state.audit("cli", "token.create", name)
        return token

    def revoke(self, name: str) -> None:
        with self.state.connect() as db:
            result = db.execute(
                "UPDATE tokens SET revoked_at=? WHERE name=? AND revoked_at IS NULL", (now(), name)
            )
        self.state.audit("cli", "token.revoke", name, ok=bool(result.rowcount))

    def authenticate(self, token: str) -> Principal:
        hashed = hashlib.sha256(token.encode()).hexdigest()
        rows = self.state.rows(
            "SELECT * FROM tokens WHERE token_hash=? AND revoked_at IS NULL", (hashed,)
        )
        stored = rows[0]["token_hash"] if rows else "0" * 64
        if (
            not hmac.compare_digest(hashed, stored)
            or not rows
            or (
                rows[0]["expires_at"]
                and datetime.fromisoformat(rows[0]["expires_at"]) <= datetime.now(UTC)
            )
        ):
            raise WikiError("E_UNAUTHORIZED", "Нужен действующий Bearer-токен.", status=401)
        if self.rate_limit:
            minute = int(time.time()) // 60
            with self.state.connect() as db:
                db.execute("DELETE FROM rate_limits WHERE minute<?", (minute,))
                db.execute(
                    "INSERT INTO rate_limits VALUES (?,?,1) ON CONFLICT(name,minute) DO UPDATE SET count=count+1",
                    (rows[0]["name"], minute),
                )
                count = db.execute(
                    "SELECT count FROM rate_limits WHERE name=? AND minute=?",
                    (rows[0]["name"], minute),
                ).fetchone()[0]
            if count > self.rate_limit:
                raise WikiError(
                    "E_RATE_LIMIT",
                    "Превышен лимит запросов токена.",
                    "Повторите запрос в следующую минуту.",
                    status=429,
                )
        return Principal.model_validate(rows[0])
