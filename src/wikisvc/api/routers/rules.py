from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from wikisvc.api.deps import Reader, Reviewer, Services, Writer
from wikisvc.services.review import review_rule

router = APIRouter(prefix="/rules")


# doc: API-wikisvc.rules.related
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


# doc: DTO-wikisvc.Promote
class Promote(BaseModel):
    model_config = ConfigDict(extra="forbid")
    level: Literal["must", "should"] = "should"
    priority: int | None = Field(default=None, ge=1, le=5)
    applies_to: list[str] | None = None
    owner: str | None = None
    enforced_by: list[str] | None = None


# doc: DTO-wikisvc.Deprecate
class Deprecate(BaseModel):
    reason: str = Field(min_length=1, max_length=200)


class Violation(BaseModel):
    rule_id: str
    note: str = Field(max_length=2000)
    ref: str = Field(default="", max_length=2000)


# doc: DTO-wikisvc.Violations
class Violations(BaseModel):
    items: list[Violation] = Field(min_length=1, max_length=100)


# doc: API-wikisvc.rules.list
@router.get("")
def list_rules(
    services: Services,
    actor: Reader,
    category: str | None = None,
    level: str | None = None,
    lifecycle: str | None = None,
    applies_to: str | None = None,
    origin: str | None = None,
    source: str | None = None,
    q: str | None = None,
    sort: str = "id",
    limit: int = 50,
    cursor: str | None = None,
) -> dict[str, Any]:
    return services.rules.list_rules(
        actor,
        category,
        level,
        lifecycle.split(",") if lifecycle else None,
        applies_to.split(",") if applies_to else None,
        origin,
        source,
        q,
        sort,
        limit,
        cursor,
    )


# doc: API-wikisvc.rules.stats
@router.get("/stats")
def stats(services: Services, actor: Reviewer, days: int = 30) -> dict[str, Any]:
    return services.rules.stats(actor, days)


# doc: API-wikisvc.rules.violations
@router.post("/violations")
def violations(payload: Violations, services: Services, actor: Writer) -> dict[str, int]:
    return services.rules.violations(actor, [i.model_dump() for i in payload.items])


# doc: API-wikisvc.rules.promote
@router.post("/{page_id}/promote")
def promote(page_id: str, payload: Promote, services: Services, actor: Reviewer) -> dict[str, Any]:
    return review_rule(services, actor, page_id, "promote", payload.model_dump(exclude_none=True))


# doc: API-wikisvc.rules.deprecate
@router.post("/{page_id}/deprecate")
def deprecate(
    page_id: str, payload: Deprecate, services: Services, actor: Reviewer
) -> dict[str, Any]:
    return review_rule(services, actor, page_id, "deprecate", payload.model_dump())


# doc: API-wikisvc.rules.get
@router.get("/{page_id}")
def get(page_id: str, services: Services, actor: Reader) -> dict[str, Any]:
    return services.rules.get(page_id, actor)
