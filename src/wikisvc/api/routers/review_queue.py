from collections import Counter
from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from wikisvc.api.deps import Reader, Reviewer, Services, Writer
from wikisvc.domain.errors import WikiError
from wikisvc.services.auth import can_read

router = APIRouter()


class Evidence(BaseModel):
    page: str
    quote: str = Field(min_length=1, max_length=4000)


class Finding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: str = Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9_-]+$")
    severity: Literal["info", "warning", "error", "critical"] = "warning"
    pages: list[str] = Field(min_length=1, max_length=20)
    summary: str = Field(min_length=3, max_length=500)
    explanation: str = Field(default="", max_length=12000)
    evidence: list[Evidence] = Field(default_factory=list, max_length=20)
    proposal_pid: str | None = None
    run_id: str | None = None


class Reason(BaseModel):
    reason: str = ""


@router.get("/whoami")
def whoami(actor: Reader) -> dict[str, Any]:
    return actor.model_dump()


@router.post("/findings")
def create_finding(payload: Finding, services: Services, actor: Writer) -> dict[str, Any]:
    return services.findings.create(actor, payload.model_dump())


@router.get("/findings")
def findings(
    services: Services,
    actor: Reader,
    status: str | None = None,
    kind: str | None = None,
    severity: str | None = None,
    limit: int = 50,
    cursor: str | None = None,
) -> dict[str, Any]:
    return services.findings.list(actor, status, kind, severity, limit, cursor)


@router.get("/findings/stats")
def finding_stats(services: Services, actor: Reader) -> dict[str, Any]:
    return services.findings.stats(actor)


@router.post("/findings/{finding_id}/dismiss")
def dismiss(
    finding_id: str, payload: Reason, services: Services, actor: Reviewer
) -> dict[str, Any]:
    return services.findings.decide(finding_id, actor, False, payload.reason)


@router.post("/findings/{finding_id}/reopen")
def reopen(finding_id: str, services: Services, actor: Reviewer) -> dict[str, Any]:
    return services.findings.decide(finding_id, actor, True)


@router.get("/inbox")
def inbox(services: Services, actor: Reviewer) -> dict[str, Any]:
    candidates: Counter[str] = Counter()
    for page in services.indexer.pages():
        if (
            page.frontmatter.type == "rule"
            and can_read(actor, page.frontmatter.sensitivity)
            and (page.frontmatter.model_extra or {}).get("lifecycle") == "candidate"
        ):
            for source in page.frontmatter.sources or ["unsourced"]:
                candidates[source] += 1
    proposals = 0
    for row in services.state.rows("SELECT pid FROM proposals WHERE status='submitted'"):
        try:
            services.proposals._proposal(row["pid"], actor)
            proposals += 1
        except WikiError as exc:
            if exc.status != 404:
                raise
    pending: int | None = None
    if actor.clearance == "restricted":
        pending = 0
        cursor = None
        while True:
            result = services.raw.list_files(actor, pending=True, limit=100, cursor=cursor)
            pending += len(result["items"])
            cursor = result["next_cursor"]
            if not cursor:
                break
    return {
        "proposals": proposals,
        "pending_sources": pending,
        "candidates_by_source": dict(candidates),
        "open_findings": len(services.findings.all(actor, "open")),
        "jobs": {"available": False, "unfinished": None},
        "lint": dict(Counter(i.code for i in services.lint.run(actor))),
    }
