"""Read-only project audit. Only findings may leave this job; never proposals/raw."""

import hashlib
from collections import defaultdict
from collections.abc import Callable
from functools import partial
from pathlib import PurePosixPath
from typing import Literal, Self

from pydantic import BaseModel, Field, ValidationError, model_validator

from wikiagent.client import WikiClient
from wikiagent.config import AgentConfig
from wikiagent.models import ModelClient
from wikiagent.planner.claims import StrictModel
from wikiagent.state import AgentState
from wikisvc.domain.errors import WikiError
from wikisvc.domain.secrets import secret_kinds
from wikisvc.domain.validate import overlaps
from wikisvc.storage.state_db import now


class AuditFile(StrictModel):
    path: str = Field(min_length=1, max_length=1024)
    text: str

    @model_validator(mode="after")
    def valid_file(self) -> Self:
        if (
            self.path.startswith("/")
            or any(part in ("", ".", "..") for part in self.path.split("/"))
            or any(c in self.path for c in "\\:\x00\r\n")
            or not self.path.endswith(".md")
            or len(self.text.encode("utf-8")) > 256 * 1024
        ):
            raise ValueError("Нужен относительный путь .md без .. и файл до 256 КиБ.")
        return self


class AuditRequest(StrictModel):
    project: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    profile: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    scopes: list[str] = Field(default_factory=list, max_length=200)
    files: list[AuditFile] = Field(min_length=1, max_length=200)

    def validate_limits(self, config: AgentConfig) -> None:
        if len(self.files) > config.docs_audit.max_files or len(
            {f.path for f in self.files}
        ) != len(self.files):
            raise WikiError(
                "E_REQUEST_INVALID", "Превышен лимит файлов или повторяется путь.", status=400
            )
        if any(not s.strip() or "," in s for s in self.scopes):
            raise WikiError("E_REQUEST_INVALID", "Некорректные scopes.", status=400)
        if sum(len(f.text.encode("utf-8")) for f in self.files) > min(
            config.docs_audit.max_total_bytes, config.max_upload_mb * 1024 * 1024
        ):
            raise WikiError(
                "E_BODY_TOO_LARGE", "Превышен суммарный размер документации.", status=413
            )
        # Reject before AgentState.job persists anything, including file names.
        if secret_kinds(self.model_dump_json(), config.secret_entropy_threshold):
            raise WikiError(
                "E_SECRET_DETECTED",
                "Уберите возможные секреты из документации перед загрузкой.",
                status=400,
            )


def parse_request(payload: object, config: AgentConfig) -> AuditRequest:
    if not config.docs_audit.enabled:
        raise WikiError(
            "E_DOCS_AUDIT_DISABLED",
            "Сверка документации выключена в настройках агента.",
            status=403,
        )
    try:
        request = AuditRequest.model_validate(payload)
    except (ValidationError, UnicodeError) as exc:
        # Pydantic's error details can echo uploaded secrets. Never return/store them.
        raise WikiError(
            "E_REQUEST_INVALID",
            "Нужны project, profile и до 200 файлов .md по 256 КиБ с относительными путями без .. .",
            status=400,
        ) from exc
    request.validate_limits(config)
    return request


class Included(BaseModel):
    id: str
    level: Literal["must", "should"]
    category: str


class Compilation(BaseModel):
    version: str
    scopes: list[str]
    included: list[Included]


class PolicyPage(BaseModel):
    id: str
    version: str
    summary: str
    body_md: str
    applies_to: list[str]


class AuditVerdict(StrictModel):
    relation: Literal["none", "violation", "wording"]
    confidence: float = Field(ge=0, le=1)
    summary: str = Field(min_length=3, max_length=500)
    line: int = Field(default=1, ge=1)
    project_quote: str = Field(default="", max_length=4000)
    policy_quote: str = Field(default="", max_length=4000)
    action: str = Field(default="", max_length=2000)


def validate_verdict(
    result: AuditVerdict, page: PolicyPage, file: AuditFile, threshold: float
) -> None:
    if secret_kinds(result.model_dump_json(), threshold):
        raise WikiError("E_SECRET_DETECTED", "Ответ содержит возможный секрет.")
    if result.relation == "none":
        return
    lines = file.text.splitlines()
    if (
        not result.project_quote.strip()
        or len(result.project_quote.split()) > 30
        or result.line > len(lines)
        or result.project_quote not in "\n".join(lines[result.line - 1 :])
        or not lines[result.line - 1].strip()
        or result.project_quote.splitlines()[0] not in lines[result.line - 1]
        or not result.policy_quote.strip()
        or result.policy_quote not in page.summary + "\n" + page.body_md
        or not result.action.strip()
        or "\n" in result.summary
    ):
        raise WikiError(
            "E_QUOTE_NOT_FOUND",
            "Нужны точные цитаты политики и строки проекта (до 30 слов), а также предлагаемое действие.",
        )


# Inverted section index avoids policy × all-files enumeration. A rule checks at
# most eight applicable files, with explicit references ranked before the rest.
SECTIONS = {
    "stack": {"stack"},
    "security": {"security.md"},
    "errors": {"errors.md", "contracts.md"},
    "logging": {"observability.md", "runtime.md"},
    "testing": {"tests.md", "testing.md", "delivery.md"},
    "architecture": {"overview.md", "domain.md", "component.md", "code.md"},
    "code-style": {"code.md", "languages.md"},
    "git": {"delivery.md"},
    "build-ci": {"delivery.md", "runtime.md"},
    "docs": {"INDEX.md", "workflow.md"},
    "process": {"flows.md", "workflow.md", "delivery.md"},
}


def select_pairs(compiled: Compilation, files: list[AuditFile]) -> list[tuple[Included, AuditFile]]:
    index: dict[str, list[AuditFile]] = defaultdict(list)
    for file in sorted(files, key=lambda f: f.path):
        for category, parts in SECTIONS.items():
            if parts.intersection(PurePosixPath(file.path).parts):
                index[category].append(file)
    return [
        (rule, file)
        for rule in sorted(compiled.included, key=lambda r: (r.level != "must", r.id))
        for file in sorted(index[rule.category], key=lambda f: (rule.id not in f.text, f.path))[:8]
    ]


class AuditProgress(StrictModel):
    checked_pairs: int = 0
    model_calls: int = 0
    findings: list[str] = Field(default_factory=list)
    discarded: list[str] = Field(default_factory=list)
    budget_exhausted: bool = False


class Pending(StrictModel):
    key: str
    verdict: AuditVerdict
    model_calls: int = 0


class DocsAudit:
    def __init__(
        self,
        client: WikiClient,
        models: ModelClient,
        state: AgentState,
        boundary: Callable[[str], None],
    ) -> None:
        self.client, self.models, self.state, self.boundary = client, models, state, boundary

    def calls(self, day: str | None = None) -> int:
        return int(
            self.state.rows(
                "SELECT COUNT(*) n FROM model_calls WHERE task='docs_audit' AND (? IS NULL OR day=?)",
                (day, day),
            )[0]["n"]
        )

    def run(self, job_id: str, payload: object) -> None:
        request = parse_request(payload, self.models.config)
        config = self.models.config.docs_audit
        params = {"profile": request.profile}
        if request.scopes:
            params["scopes"] = ",".join(request.scopes)
        compiled = Compilation.model_validate(
            self.client.request("GET", "/policies/compile", params=params)
        )
        progress = AuditProgress.model_validate(self.state.restore(job_id, "report", {}))
        progress.budget_exhausted = False
        calls_before = self.calls()
        findings_before = len(progress.findings)
        for rule, file in select_pairs(compiled, request.files):
            self.boundary(job_id)
            digest = hashlib.sha256((compiled.version + file.text).encode()).hexdigest()
            pair = (
                "docs_audit:" + rule.id,
                compiled.version,
                request.project + "/" + file.path,
                digest,
            )
            key = hashlib.sha256("\0".join(pair).encode()).hexdigest()
            if self.state.rows(
                "SELECT verdict FROM pair_checks WHERE a_id=? AND a_hash=? AND b_id=? AND b_hash=?",
                pair,
            ):
                continue
            attempts = min(
                config.max_model_calls_per_run - (self.calls() - calls_before),
                config.max_model_calls_per_day - self.calls(now()[:10]),
                self.models.config.limits.retries,
            )
            pending = self.state.restore(job_id, "pending")
            cached = Pending.model_validate(pending) if pending else None
            if len(progress.findings) - findings_before >= config.max_findings_per_run or (
                attempts <= 0 and not (cached and cached.key == key)
            ):
                progress.budget_exhausted = True
                break
            page = PolicyPage.model_validate(self.client.request("GET", "/pages/" + rule.id))
            if not overlaps(page.applies_to, compiled.scopes):
                continue
            validator = partial(
                validate_verdict,
                page=page,
                file=file,
                threshold=self.models.config.secret_entropy_threshold,
            )
            if cached and cached.key == key:
                verdict = cached.verdict
                pair_calls = cached.model_calls
                validator(verdict)
            else:
                pair_start = self.calls()
                try:
                    verdict = self.models.structured(
                        "planner",
                        "docs_audit",
                        AuditVerdict,
                        {
                            "policy": page.model_dump(),
                            "level": rule.level,
                            "project": request.project,
                            "untrusted_external": file.model_dump(),
                        },
                        validator,
                        max_attempts=attempts,
                    )
                except WikiError as exc:
                    if exc.code != "E_MODEL_OUTPUT":
                        raise
                    # Store only a code, never model output or validation details.
                    progress.discarded.append(exc.code)
                    verdict = AuditVerdict(relation="none", confidence=0, summary=exc.code)
                pair_calls = self.calls() - pair_start
                self.state.checkpoint(
                    job_id,
                    "pending",
                    Pending(key=key, verdict=verdict, model_calls=pair_calls).model_dump(),
                )
            self.boundary(job_id)
            if verdict.relation != "none" and verdict.confidence >= config.confidence_threshold:
                current = PolicyPage.model_validate(self.client.request("GET", "/pages/" + rule.id))
                latest = Compilation.model_validate(
                    self.client.request("GET", "/policies/compile", params=params)
                )
                if current.version != page.version or latest.version != compiled.version:
                    raise WikiError(
                        "E_AUDIT_STALE",
                        "Политики изменились во время сверки; возобновите задачу.",
                        status=409,
                    )
                finding = self.client.request(
                    "POST",
                    "/findings",
                    json={
                        "kind": "docs-audit",
                        "severity": "info"
                        if verdict.relation == "wording"
                        else "error"
                        if rule.level == "must"
                        else "warning",
                        "pages": [rule.id],
                        "summary": verdict.summary,
                        "explanation": f"{request.project} {file.path}:{verdict.line}\nЦитата проекта: {verdict.project_quote}\nПредлагаемое действие: {verdict.action}",
                        "evidence": [{"page": rule.id, "quote": verdict.policy_quote}],
                        "proposal_pid": None,
                        "run_id": job_id,
                        "scope": request.project,
                    },
                )
                if finding["id"] not in progress.findings:
                    progress.findings.append(finding["id"])
            # Pending precedes POST: a crash after POST replays the same request;
            # the existing service fingerprint makes delivery idempotent.
            with self.state.connect() as db:
                db.execute(
                    "INSERT OR REPLACE INTO pair_checks VALUES (?,?,?,?,?,?,?)",
                    (*pair, verdict.model_dump_json(), verdict.confidence, now()),
                )
                progress.checked_pairs += 1
                progress.model_calls += pair_calls
                db.execute(
                    "INSERT OR REPLACE INTO job_state VALUES (?,?,?)",
                    (job_id, "report", progress.model_dump_json()),
                )
                db.execute("DELETE FROM job_state WHERE job_id=? AND key='pending'", (job_id,))
            self.state.status(job_id, "running", progress.model_dump())
        self.state.checkpoint(job_id, "report", progress.model_dump())
        self.state.status(
            job_id,
            "paused" if progress.budget_exhausted else "awaiting_review",
            progress.model_dump(),
        )
