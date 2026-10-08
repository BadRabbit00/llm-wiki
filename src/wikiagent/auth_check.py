"""Read-only SSO deployment diagnostics; never authenticate the issuer over HTTP."""

import os
import sqlite3
import ssl
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from wikisvc.services.sessions import load_roles


def check_authentication(http: httpx.Client | None = None) -> list[str]:
    issuer_name = os.environ.get("SESSION_ISSUER_TOKEN_NAME", "")
    if not issuer_name:
        return []
    roles = load_roles(Path(os.environ.get("ROLES_FILE", "/etc/llm-wiki/roles.yaml")))
    path = Path(os.environ.get("STATE_DIR", "/var/lib/llm-wiki/state")) / "state.db"
    try:
        with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as db:
            row = db.execute(
                "SELECT kind,role,clearance,revoked_at,expires_at FROM tokens WHERE name=?",
                (issuer_name,),
            ).fetchone()
    except sqlite3.Error as exc:
        raise ValueError("Cannot inspect the session issuer in local state.db") from exc
    if row is None or row[3]:
        raise ValueError("Session issuer token is missing or revoked")
    if row[:3] != ("agent", "reader", "public"):
        raise ValueError("Session issuer must be kind=agent role=reader clearance=public")
    if row[4] and datetime.fromisoformat(row[4]) <= datetime.now(UTC):
        raise ValueError("Session issuer token has expired")
    messages = ["session issuer: valid (local DB); roles: " + ", ".join(sorted(roles.groups))]
    issuer = os.environ.get("WIKI_UI_OIDC_ISSUER", "")
    address = urlsplit(issuer)
    if address.scheme != "https" or not address.hostname or address.username:
        messages.append("WARN OIDC discovery: configure an HTTPS issuer in ui.env")
    else:
        try:
            if http is None:
                context = ssl.create_default_context(cafile=os.environ.get("SSL_CERT_FILE"))
                with httpx.Client(
                    timeout=httpx.Timeout(10, connect=5),
                    follow_redirects=False,
                    trust_env=False,
                    verify=context,
                ) as client:
                    available = _discovery(client, issuer)
            else:
                available = _discovery(http, issuer)
            messages.append(
                "OIDC discovery: ready" if available else "WARN OIDC discovery: unavailable"
            )
        except (httpx.HTTPError, OSError, ValueError):
            messages.append("WARN OIDC discovery: unavailable (check network, issuer and CA)")
    try:
        result = subprocess.run(
            ["timedatectl", "show", "--property=NTPSynchronized", "--value"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        synced = result.returncode == 0 and result.stdout.strip() == "yes"
    except (OSError, subprocess.TimeoutExpired):
        synced = False
    messages.append("NTP: synchronized" if synced else "WARN NTP: verify clock synchronization")
    return messages


def _discovery(http: httpx.Client, issuer: str) -> bool:
    response = http.get(issuer.rstrip("/") + "/.well-known/openid-configuration")
    response.raise_for_status()
    metadata = response.json()
    return isinstance(metadata, dict) and metadata.get("issuer") == issuer
