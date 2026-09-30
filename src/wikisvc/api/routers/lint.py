from typing import Any

from fastapi import APIRouter

from wikisvc.api.deps import Reader, Services
from wikisvc.services.pages import paginate

router = APIRouter()


@router.get("/lint")
def lint(
    services: Services, actor: Reader, limit: int = 50, cursor: str | None = None
) -> dict[str, Any]:
    result = paginate([issue.model_dump() for issue in services.lint.run(actor)], limit, cursor)
    return {"issues": result["items"], "next_cursor": result["next_cursor"]}


@router.get("/stats")
def stats(services: Services, actor: Reader) -> dict[str, Any]:
    return services.lint.stats(actor)
