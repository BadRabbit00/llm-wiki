from typing import Any

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from wikisvc.api.deps import Reader, Reviewer, Services
from wikisvc.services.review import review

router = APIRouter()


class OutdatedRequest(BaseModel):
    reason: str


@router.post("/pages/{page_id}/verify")
def verify(page_id: str, services: Services, actor: Reviewer) -> dict[str, Any]:
    return review(services, actor, page_id, True)


@router.post("/pages/{page_id}/mark-outdated")
def mark_outdated(
    page_id: str, payload: OutdatedRequest, services: Services, actor: Reviewer
) -> dict[str, Any]:
    return review(services, actor, page_id, False, payload.reason)


@router.get("/pages")
def list_pages(
    services: Services,
    actor: Reader,
    type: str | None = None,
    status: str | None = None,
    tag: str | None = None,
    q_title: str | None = None,
    limit: int = 50,
    cursor: str | None = None,
) -> dict[str, Any]:
    return services.pages.list_pages(actor, type, status, tag, q_title, limit, cursor)


@router.get("/pages/{page_id}")
def get_page(
    page_id: str, services: Services, actor: Reader, include: str = "", format: str = "json"
) -> Any:
    result = services.pages.get(page_id, actor, include, format)
    return PlainTextResponse(result) if isinstance(result, str) else result


@router.get("/pages/{page_id}/history")
def history(
    page_id: str, services: Services, actor: Reader, limit: int = 50, cursor: str | None = None
) -> dict[str, Any]:
    from wikisvc.services.pages import paginate

    return paginate(list(services.pages.history(page_id, actor)), limit, cursor)


@router.get("/pages/{page_id}/at/{commit}")
def at(page_id: str, commit: str, services: Services, actor: Reader) -> dict[str, Any]:
    return services.pages.at(page_id, commit, actor)


@router.get("/index", response_class=PlainTextResponse)
def index(services: Services, actor: Reader) -> str:
    return services.pages.index(actor)
