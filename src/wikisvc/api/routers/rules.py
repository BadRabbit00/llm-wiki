from typing import Any

from fastapi import APIRouter

from wikisvc.api.deps import Reader, Services

router = APIRouter(prefix="/rules")


@router.get("/related")
def related(
    services: Services,
    actor: Reader,
    q: str,
    scopes: str | None = None,
    limit: int = 10,
    impact_terms: str | None = None,
) -> dict[str, Any]:
    return services.rules.related(
        q,
        actor,
        scopes.split(",") if scopes else None,
        limit,
        impact_terms.split(",") if impact_terms else None,
    )


@router.get("/{page_id}")
def get(page_id: str, services: Services, actor: Reader) -> dict[str, Any]:
    return services.rules.get(page_id, actor)
