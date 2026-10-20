from typing import Annotated, Any, Literal

from fastapi import APIRouter, Body, Header
from pydantic import BaseModel, Field

from wikisvc.api.deps import Reader, Reviewer, Services, Writer
from wikisvc.api.routers.rules import Deprecate, Promote
from wikisvc.domain.ids import check_page_id
from wikisvc.domain.markdown import parse

router = APIRouter(prefix="/proposals")


# doc: DTO-wikisvc.CreateProposal
class CreateProposal(BaseModel):
    title: str
    description: str = ""
    kind: Literal["manual", "chat", "book", "heal"] = "manual"


# doc: DTO-wikisvc.PutPage
class PutPage(BaseModel):
    frontmatter: dict[str, Any]
    body_md: str
    base_version: str | None = None


# doc: DTO-wikisvc.PatchPage
class PatchPage(BaseModel):
    ops: list[dict[str, Any]] = Field(min_length=1, max_length=100)
    base_version: str | None = None


# doc: DTO-wikisvc.Comment
class Comment(BaseModel):
    comment: str = ""
    reason: str = ""


# doc: API-wikisvc.proposals.create
@router.post("")
def create(payload: CreateProposal, services: Services, actor: Writer) -> dict[str, Any]:
    return services.proposals.create(actor, payload.title, payload.description, payload.kind)


# doc: API-wikisvc.proposals.list
@router.get("")
def list_proposals(
    services: Services,
    actor: Reader,
    status: str | None = None,
    author: str | None = None,
    limit: int = 50,
    cursor: str | None = None,
    kind: str | None = None,
) -> dict[str, Any]:
    return services.proposals.list_proposals(actor, status, author, limit, cursor, kind)


# doc: API-wikisvc.proposals.get
@router.get("/{pid}")
def get(pid: str, services: Services, actor: Reader) -> dict[str, Any]:
    return services.proposals.get(pid, actor)


# doc: API-wikisvc.proposals.put-page
@router.put("/{pid}/pages/{page_id}")
def put(
    pid: str,
    page_id: str,
    payload: Annotated[PutPage | str, Body()],
    services: Services,
    actor: Writer,
    base_version: Annotated[str | None, Header(alias="If-Match")] = None,
) -> dict[str, Any]:
    check_page_id(services.registry, page_id)
    if isinstance(payload, str):
        metadata, body = parse(payload)
        return services.proposals.put(pid, page_id, actor, metadata, body, base_version)
    return services.proposals.put(
        pid, page_id, actor, payload.frontmatter, payload.body_md, payload.base_version
    )


# doc: API-wikisvc.proposals.patch-page
@router.patch("/{pid}/pages/{page_id}")
def patch(
    pid: str, page_id: str, payload: PatchPage, services: Services, actor: Writer
) -> dict[str, Any]:
    check_page_id(services.registry, page_id)
    return services.proposals.patch(pid, page_id, actor, payload.ops, payload.base_version)


# doc: API-wikisvc.proposals.delete-page
@router.delete("/{pid}/pages/{page_id}")
def delete(
    pid: str, page_id: str, services: Services, actor: Writer, base_version: str | None = None
) -> dict[str, str]:
    check_page_id(services.registry, page_id)
    return services.proposals.delete(pid, page_id, actor, base_version)


# doc: API-wikisvc.proposals.validate
@router.get("/{pid}/validate")
def validate(pid: str, services: Services, actor: Writer) -> dict[str, Any]:
    return services.proposals.validate(pid, actor)


# doc: API-wikisvc.proposals.diff
@router.get("/{pid}/diff")
def diff(pid: str, services: Services, actor: Reader) -> dict[str, Any]:
    return services.proposals.diff(pid, actor)


# doc: API-wikisvc.proposals.impact
@router.get("/{pid}/impact")
def impact(pid: str, services: Services, actor: Reader) -> dict[str, Any]:
    return services.rules.proposal_impact(pid, actor)


# doc: API-wikisvc.proposals.submit
@router.post("/{pid}/submit")
def submit(pid: str, services: Services, actor: Writer) -> dict[str, Any]:
    return services.proposals.submit(pid, actor)


class PromoteItem(Promote):
    id: str


class DeprecateItem(Deprecate):
    id: str


# doc: DTO-wikisvc.Accept
class Accept(BaseModel):
    promote: list[PromoteItem] = Field(default_factory=list, max_length=100)
    deprecate: list[DeprecateItem] = Field(default_factory=list, max_length=100)


# doc: API-wikisvc.proposals.accept
@router.post("/{pid}/accept")
def accept(
    pid: str, services: Services, actor: Reviewer, payload: Accept | None = None
) -> dict[str, Any]:
    body = payload or Accept()
    return services.proposals.decide(
        pid,
        actor,
        "accepted",
        promote=[i.model_dump(exclude_none=True) for i in body.promote],
        deprecate=[i.model_dump() for i in body.deprecate],
    )


# doc: API-wikisvc.proposals.revert
@router.post("/{pid}/revert")
def revert(pid: str, services: Services, actor: Reviewer) -> dict[str, Any]:
    return services.proposals.revert(pid, actor)


# doc: API-wikisvc.proposals.notes
@router.put("/{pid}/notes")
def notes(pid: str, payload: dict[str, Any], services: Services, actor: Writer) -> dict[str, Any]:
    return services.proposals.put_notes(pid, actor, payload)


# doc: API-wikisvc.proposals.reject
@router.post("/{pid}/reject")
def reject(pid: str, payload: Comment, services: Services, actor: Reviewer) -> dict[str, Any]:
    return services.proposals.decide(pid, actor, "rejected", payload.reason)


# doc: API-wikisvc.proposals.request-changes
@router.post("/{pid}/request-changes")
def request_changes(
    pid: str, payload: Comment, services: Services, actor: Reviewer
) -> dict[str, Any]:
    return services.proposals.decide(pid, actor, "changes_requested", payload.comment)


# doc: API-wikisvc.proposals.abandon
@router.post("/{pid}/abandon")
def abandon(pid: str, services: Services, actor: Writer) -> dict[str, Any]:
    return services.proposals.decide(pid, actor, "abandoned")
