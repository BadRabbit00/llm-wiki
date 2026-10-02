from typing import Annotated, Any

from fastapi import APIRouter, Query

from wikisvc.api.deps import Reader, Services

router = APIRouter(prefix="/graph")


@router.get("/impact/{page_id}")
def impact(
    page_id: str, services: Services, actor: Reader, depth: int = 2, rels: str | None = None
) -> dict[str, Any]:
    return services.graph.impact(page_id, actor, depth, rels.split(",") if rels else None)


@router.get("/neighbors/{page_id}")
def neighbors(
    page_id: str,
    services: Services,
    actor: Reader,
    depth: int = 1,
    rels: str | None = None,
    direction: str = "both",
) -> dict[str, Any]:
    return services.graph.neighbors(
        page_id, actor, depth, rels.split(",") if rels else None, direction
    )


@router.get("/path")
def path(
    source: Annotated[str, Query(alias="from")],
    to: str,
    services: Services,
    actor: Reader,
    max_depth: int = 5,
) -> dict[str, Any]:
    return services.graph.path(source, to, actor, max_depth)


@router.get("/export")
def export(
    services: Services,
    actor: Reader,
    type: str | None = None,
    status: str | None = None,
    include_scopes: bool = False,
) -> dict[str, Any]:
    return services.graph.export(actor, type, status, include_scopes)
