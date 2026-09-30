from typing import Annotated, Any

from fastapi import APIRouter, Body, Header
from pydantic import BaseModel, Field

from wikisvc.api.deps import Reader, Reviewer, Services, Writer
from wikisvc.domain.markdown import parse

router = APIRouter(prefix="/proposals")


class CreateProposal(BaseModel):
    title: str
    description: str = ""


class PutPage(BaseModel):
    frontmatter: dict[str, Any]
    body_md: str
    base_version: str | None = None


class PatchPage(BaseModel):
    ops: list[dict[str, Any]] = Field(min_length=1, max_length=100)
    base_version: str | None = None


class Comment(BaseModel):
    comment: str = ""
    reason: str = ""


@router.post("")
def create(payload: CreateProposal, services: Services, actor: Writer) -> dict[str, Any]:
    return services.proposals.create(actor, payload.title, payload.description)


@router.get("")
def list_proposals(
    services: Services,
    actor: Reader,
    status: str | None = None,
    author: str | None = None,
    limit: int = 50,
    cursor: str | None = None,
) -> dict[str, Any]:
    return services.proposals.list_proposals(actor, status, author, limit, cursor)


@router.get("/{pid}")
def get(pid: str, services: Services, actor: Reader) -> dict[str, Any]:
    return services.proposals.get(pid, actor)


@router.put("/{pid}/pages/{page_id}")
def put(
    pid: str,
    page_id: str,
    payload: Annotated[PutPage | str, Body()],
    services: Services,
    actor: Writer,
    base_version: Annotated[str | None, Header(alias="If-Match")] = None,
) -> dict[str, Any]:
    if isinstance(payload, str):
        metadata, body = parse(payload)
        return services.proposals.put(pid, page_id, actor, metadata, body, base_version)
    return services.proposals.put(
        pid, page_id, actor, payload.frontmatter, payload.body_md, payload.base_version
    )


@router.patch("/{pid}/pages/{page_id}")
def patch(
    pid: str, page_id: str, payload: PatchPage, services: Services, actor: Writer
) -> dict[str, Any]:
    return services.proposals.patch(pid, page_id, actor, payload.ops, payload.base_version)


@router.delete("/{pid}/pages/{page_id}")
def delete(
    pid: str, page_id: str, services: Services, actor: Writer, base_version: str | None = None
) -> dict[str, str]:
    return services.proposals.delete(pid, page_id, actor, base_version)


@router.get("/{pid}/validate")
def validate(pid: str, services: Services, actor: Writer) -> dict[str, Any]:
    return services.proposals.validate(pid, actor)


@router.get("/{pid}/diff")
def diff(pid: str, services: Services, actor: Reader) -> dict[str, Any]:
    return services.proposals.diff(pid, actor)


@router.post("/{pid}/submit")
def submit(pid: str, services: Services, actor: Writer) -> dict[str, Any]:
    return services.proposals.submit(pid, actor)


@router.post("/{pid}/accept")
def accept(pid: str, services: Services, actor: Reviewer) -> dict[str, Any]:
    return services.proposals.decide(pid, actor, "accepted")


@router.post("/{pid}/reject")
def reject(pid: str, payload: Comment, services: Services, actor: Reviewer) -> dict[str, Any]:
    return services.proposals.decide(pid, actor, "rejected", payload.reason)


@router.post("/{pid}/request-changes")
def request_changes(
    pid: str, payload: Comment, services: Services, actor: Reviewer
) -> dict[str, Any]:
    return services.proposals.decide(pid, actor, "changes_requested", payload.comment)


@router.post("/{pid}/abandon")
def abandon(pid: str, services: Services, actor: Writer) -> dict[str, Any]:
    return services.proposals.decide(pid, actor, "abandoned")
