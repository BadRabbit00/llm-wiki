import hashlib
import json
import uuid
from typing import TYPE_CHECKING, Any

from wikisvc.domain.errors import WikiError, not_found
from wikisvc.domain.models import Principal
from wikisvc.domain.secrets import secret_kinds
from wikisvc.services.auth import require_human, require_role
from wikisvc.services.pages import paginate
from wikisvc.storage.lock import write_lock
from wikisvc.storage.state_db import now

if TYPE_CHECKING:
    from wikisvc.services.runtime import Runtime


class Findings:
    def __init__(self, runtime: "Runtime") -> None:
        self.rt = runtime

    def visible(self, row: dict[str, Any], actor: Principal) -> dict[str, Any]:
        result = dict(row)
        for field in ("pages", "evidence"):
            result[field] = json.loads(row[field])
        for page_id in result["pages"]:
            self.rt.pages.page(page_id, actor)
        if result["proposal_pid"]:
            self.rt.proposals._proposal(result["proposal_pid"], actor)
        return result

    def create(self, actor: Principal, values: dict[str, Any]) -> dict[str, Any]:
        require_role(actor, "writer")
        with write_lock(self.rt.settings.state_dir, self.rt.settings.lock_timeout):
            pages = {page_id: self.rt.pages.page(page_id, actor) for page_id in values["pages"]}
            for evidence in values.get("evidence", []):
                quote, page_id = evidence["quote"], evidence["page"]
                if (
                    page_id not in pages
                    or not quote.strip()
                    or " ".join(quote.casefold().split())
                    not in " ".join(
                        (pages[page_id].frontmatter.summary + "\n" + pages[page_id].body_md)
                        .casefold()
                        .split()
                    )
                ):
                    raise WikiError("E_QUOTE_NOT_FOUND", "Доказательство не найдено в странице.")
            data = json.dumps(values, ensure_ascii=False)
            if len(data) > 100000:
                raise WikiError("E_REQUEST_INVALID", "Находка слишком велика.", status=400)
            if secret_kinds(data, self.rt.settings.secret_entropy_threshold):
                raise WikiError("E_SECRET_DETECTED", "Находка содержит возможный секрет.")
            if values.get("proposal_pid"):
                proposal = self.rt.proposals._proposal(values["proposal_pid"], actor)
                if proposal.author != actor.name:
                    raise WikiError(
                        "E_FORBIDDEN", "Находку можно связать со своим предложением.", status=403
                    )
            fingerprint = hashlib.sha256(
                json.dumps(
                    [values["kind"], sorted((p.id, p.version) for p in pages.values())]
                ).encode()
            ).hexdigest()
            existing = self.rt.state.rows(
                "SELECT * FROM findings WHERE fingerprint=?", (fingerprint,)
            )
            if existing:
                # Dismissal and resolution survive identical evidence being posted again.
                return self.visible(existing[0], actor)
            row = {
                "id": uuid.uuid4().hex,
                "kind": values["kind"],
                "severity": values["severity"],
                "status": "open",
                "pages": json.dumps(sorted(pages)),
                "summary": values["summary"],
                "explanation": values.get("explanation", ""),
                "evidence": json.dumps(values.get("evidence", [])),
                "proposal_pid": values.get("proposal_pid"),
                "run_id": values.get("run_id"),
                "fingerprint": fingerprint,
                "created_at": now(),
                "updated_at": now(),
                "reason": None,
            }
            with self.rt.state.connect() as db:
                db.execute(
                    "INSERT INTO findings(id,kind,severity,status,pages,summary,explanation,evidence,proposal_pid,run_id,fingerprint,created_at,reason,updated_at) VALUES (:id,:kind,:severity,:status,:pages,:summary,:explanation,:evidence,:proposal_pid,:run_id,:fingerprint,:created_at,:reason,:updated_at)",
                    row,
                )
            self.rt.state.audit(actor.name, "finding.create", row["id"])
            return self.visible(row, actor)

    def all(
        self,
        actor: Principal,
        status: str | None = None,
        kind: str | None = None,
        severity: str | None = None,
    ) -> list[dict[str, Any]]:
        result = []
        for row in self.rt.state.rows(
            "SELECT * FROM findings WHERE (? IS NULL OR status=?) AND (? IS NULL OR kind=?) AND (? IS NULL OR severity=?) ORDER BY created_at,id",
            (status, status, kind, kind, severity, severity),
        ):
            try:
                result.append(self.visible(row, actor))
            except WikiError as exc:
                if exc.status != 404:
                    raise
        return result

    def list(
        self,
        actor: Principal,
        status: str | None = None,
        kind: str | None = None,
        severity: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        return paginate(self.all(actor, status, kind, severity), limit, cursor)

    def decide(
        self, finding_id: str, actor: Principal, reopen: bool, reason: str = ""
    ) -> dict[str, Any]:
        require_human(actor)
        if not reopen and (not reason.strip() or len(reason) > 2000):
            raise WikiError(
                "E_REQUEST_INVALID", "Для отклонения нужна причина до 2000 символов.", status=400
            )
        if secret_kinds(reason, self.rt.settings.secret_entropy_threshold):
            raise WikiError("E_SECRET_DETECTED", "Причина содержит возможный секрет.")
        with write_lock(self.rt.settings.state_dir, self.rt.settings.lock_timeout):
            rows = self.rt.state.rows("SELECT * FROM findings WHERE id=?", (finding_id,))
            if not rows:
                raise not_found()
            self.visible(rows[0], actor)
            with self.rt.state.connect() as db:
                db.execute(
                    "UPDATE findings SET status=?,reason=?,updated_at=? WHERE id=?",
                    (
                        "open" if reopen else "dismissed",
                        None if reopen else reason,
                        now(),
                        finding_id,
                    ),
                )
            self.rt.state.audit(
                actor.name, "finding.reopen" if reopen else "finding.dismiss", finding_id
            )
        return self.visible(
            self.rt.state.rows("SELECT * FROM findings WHERE id=?", (finding_id,))[0], actor
        )

    def stats(self, actor: Principal) -> dict[str, Any]:
        result: dict[str, dict[str, Any]] = {}
        for row in self.all(actor):
            counts = result.setdefault(row["kind"], {"open": 0, "resolved": 0, "dismissed": 0})
            counts[row["status"]] += 1
        for counts in result.values():
            decided = counts["resolved"] + counts["dismissed"]
            counts["recommendation"] = (
                "Поднять порог уверенности"
                if decided and counts["dismissed"] / decided > 0.5
                else None
            )
        return {"kinds": result}
