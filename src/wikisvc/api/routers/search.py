from typing import Any

from fastapi import APIRouter

from wikisvc.api.deps import Reader, Services

router = APIRouter()


@router.get("/search")
def search(
    q: str,
    services: Services,
    actor: Reader,
    type: str | None = None,
    tag: str | None = None,
    status: str | None = None,
    sensitivity: str | None = None,
    k: int = 10,
    mode: str = "hybrid",
    expand: bool = False,
) -> dict[str, Any]:
    return services.search.search(q, actor, type, tag, status, sensitivity, k, mode, expand)


@router.get("/context/{page_id}")
def context(
    page_id: str,
    services: Services,
    actor: Reader,
    depth: int = 1,
    rels: str | None = None,
    budget_chars: int | None = None,
) -> dict[str, Any]:
    return services.context.get(
        page_id,
        actor,
        depth,
        rels.split(",") if rels else None,
        budget_chars if budget_chars is not None else services.settings.context_budget_default,
    )
