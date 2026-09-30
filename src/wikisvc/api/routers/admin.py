from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from wikisvc.api.deps import Admin, Services
from wikisvc.domain.errors import not_found
from wikisvc.services.pages import paginate
from wikisvc.storage.lock import write_lock

router = APIRouter(prefix="/admin")


class ReindexRequest(BaseModel):
    full: bool = True


@router.post("/reindex")
def reindex(payload: ReindexRequest, services: Services, actor: Admin) -> dict[str, str]:
    with write_lock(services.settings.state_dir, services.settings.lock_timeout):
        services.reindex(payload.full)
        services.state.audit(actor.name, "admin.reindex")
    return {"status": "ok"}


@router.get("/audit")
def audit(
    services: Services,
    actor: Admin,
    since: str | None = None,
    token: str | None = None,
    action: str | None = None,
    limit: int = 50,
    cursor: str | None = None,
) -> dict[str, Any]:
    if actor.clearance != "restricted":
        raise not_found()
    rows = services.state.rows(
        "SELECT * FROM audit WHERE (? IS NULL OR ts>=?) AND (? IS NULL OR token_name=?) AND (? IS NULL OR action=?) ORDER BY ts",
        (since, since, token, token, action, action),
    )
    return paginate(rows, limit, cursor)
