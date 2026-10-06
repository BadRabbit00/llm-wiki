import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import Any

from wikiagent.chat.loop import Chat
from wikiagent.client import WikiClient
from wikiagent.heal.findings import FindingWriter
from wikiagent.heal.pairs import pairs
from wikiagent.heal.verdicts import Fix, Verdict, validate_verdict
from wikiagent.models import ModelClient
from wikiagent.state import AgentState
from wikisvc.domain.errors import WikiError
from wikisvc.storage.state_db import now


class Healer:
    def __init__(
        self,
        client: WikiClient,
        models: ModelClient,
        state: AgentState,
        chat: Chat,
        boundary: Callable[[str], None],
    ) -> None:
        self.client, self.models, self.state, self.chat, self.boundary = (
            client,
            models,
            state,
            chat,
            boundary,
        )
        self.writer = FindingWriter(client, models)
        self.existing: set[str] = set()

    def wait_chat(self, job_id: str) -> None:
        self.boundary(job_id)
        with self.chat.condition:
            waiting = False
            while self.chat.active:
                if not waiting:
                    self.state.status(job_id, "waiting_chat")
                    waiting = True
                self.chat.condition.wait(timeout=0.2)
                self.boundary(job_id)
            if waiting:
                self.state.status(job_id, "running")

    def calls(self, day: str | None = None) -> int:
        return int(
            self.state.rows(
                "SELECT COUNT(*) n FROM model_calls WHERE task LIKE 'heal_%' AND (? IS NULL OR day=?)",
                (day, day),
            )[0]["n"]
        )

    def run(self, job_id: str, payload: dict[str, Any]) -> None:
        config = self.models.config.heal
        self.existing = {f["id"] for f in self.client.all("/findings")}
        snapshots = {
            p["id"]: p for p in self.client.all("/rules", lifecycle="candidate,active,deprecated")
        }
        previous = self.state.restore("heal", "hashes", {})
        changed = {key for key, p in snapshots.items() if previous.get(key) != p["version"]}
        full = payload.get("scope", "changed") == "full"
        candidates = pairs(self.client, snapshots, changed, full, config.k_candidates)
        calls_before = self.calls()
        findings: list[str] = []
        discarded: list[dict[str, Any]] = []
        checked = 0
        exhausted = False
        incomplete = False
        for a, b in candidates:
            self.wait_chat(job_id)
            a_hash, b_hash = snapshots[a]["version"], snapshots[b]["version"]
            if self.state.rows(
                "SELECT verdict FROM pair_checks WHERE a_id=? AND a_hash=? AND b_id=? AND b_hash=?",
                (a, a_hash, b, b_hash),
            ):
                continue
            reserve = self.models.config.limits.retries * (
                2 if any(snapshots[p]["level"] == "must" for p in (a, b)) else 1
            )
            if (
                self.calls() - calls_before + reserve > config.max_model_calls_per_run
                or self.calls(now()[:10]) + reserve > config.max_model_calls_per_day
                or len(findings) >= config.max_findings_per_run
            ):
                exhausted = True
                break
            pages = {key: self.client.request("GET", "/pages/" + key) for key in (a, b)}
            # A changed snapshot is retried on the next run, never cached under an old hash.
            if any(pages[key]["version"] != snapshots[key]["version"] for key in pages):
                incomplete = True
                continue
            try:
                verdict = self.models.structured(
                    "planner",
                    "heal_pair",
                    Verdict,
                    {"pages": list(pages.values())},
                    partial(validate_verdict, pages=pages),
                )
                if (
                    verdict.relation == "conflicts"
                    and any(p.get("level") == "must" for p in pages.values())
                    and verdict.confidence >= config.confidence_threshold
                ):
                    self.wait_chat(job_id)
                    second = self.models.structured(
                        "reviewer",
                        "heal_review",
                        Verdict,
                        {"pages": list(pages.values()), "first_verdict": verdict.model_dump()},
                        partial(validate_verdict, pages=pages),
                    )
                    if (
                        second.relation != "conflicts"
                        or second.confidence < config.confidence_threshold
                    ):
                        verdict = Verdict(
                            relation="none",
                            confidence=second.confidence,
                            explanation="Второе мнение не подтвердило конфликт.",
                        )
                if verdict.relation != "none" and verdict.confidence >= config.confidence_threshold:
                    current = {key: self.client.request("GET", "/pages/" + key) for key in pages}
                    if any(current[key]["version"] != pages[key]["version"] for key in pages):
                        incomplete = True
                        continue
                    finding = self.writer.create(
                        verdict.relation,
                        verdict.explanation,
                        verdict.explanation,
                        pages,
                        [e.model_dump() for e in verdict.evidence],
                        verdict.suggested_fix,
                        job_id,
                        "error"
                        if any(p.get("level") == "must" for p in pages.values())
                        else "warning",
                    )
                    if finding["status"] == "open" and finding["id"] not in self.existing:
                        findings.append(finding["id"])
            except WikiError as exc:
                discarded.append({"pair": [a, b], "code": exc.code})
                if exc.code != "E_MODEL_OUTPUT":
                    incomplete = True
                    continue
                verdict = Verdict(relation="none", confidence=0, explanation=exc.code)
            with self.state.connect() as db:
                db.execute(
                    "INSERT OR REPLACE INTO pair_checks VALUES (?,?,?,?,?,?,?)",
                    (a, a_hash, b, b_hash, verdict.model_dump_json(), verdict.confidence, now()),
                )
            checked += 1
            self.state.status(
                job_id,
                "running",
                {"checked_pairs": checked, "findings": findings, "discarded": discarded},
            )
        if not exhausted:
            exhausted = not self.deterministic(job_id, snapshots, findings)
        if not exhausted and not incomplete:
            self.state.checkpoint(
                "heal", "hashes", {key: p["version"] for key, p in snapshots.items()}
            )
            self.state.checkpoint("heal", "last_run", now())
            if full:
                self.state.checkpoint("heal", "last_full", now())
        report = {
            "checked_pairs": checked,
            "model_calls": self.calls() - calls_before,
            "findings": list(dict.fromkeys(findings)),
            "discarded": discarded,
            "budget_exhausted": exhausted,
            "retry_needed": incomplete,
        }
        self.state.checkpoint(job_id, "report", report)
        self.state.status(job_id, "paused" if exhausted or incomplete else "done", report)

    def deterministic(
        self, job_id: str, pages: dict[str, dict[str, Any]], findings: list[str]
    ) -> bool:
        # Revisit counters/time-based lint even when page content did not change. The
        # service fingerprints findings, so dismissals remain effective without LLM calls.
        issues: list[dict[str, Any]] = []
        cursor = None
        while True:
            result = self.client.request(
                "GET", "/lint", params={"limit": 100, **({"cursor": cursor} if cursor else {})}
            )
            issues.extend(result["issues"])
            cursor = result["next_cursor"]
            if not cursor:
                break
        deadline = (
            datetime.now(UTC) - timedelta(days=self.models.config.heal.candidate_stale_days)
        ).isoformat()
        for page in pages.values():
            for code, applies in [
                (
                    "W_CANDIDATE_STALE",
                    page["lifecycle"] == "candidate" and page["updated"] < deadline,
                ),
                ("W_RULE_UNUSED", bool(page["delivered"] and not page["opened"])),
                ("W_RULE_VIOLATED", page["violations"] >= 3),
            ]:
                if applies:
                    issues.append({"code": code, "page": page["id"], "message": code})
        for problem in issues:
            self.wait_chat(job_id)
            ids = (
                [problem["page"]]
                if isinstance(problem["page"], str)
                and re.fullmatch(r"[a-z]+-[a-z0-9-]+", problem["page"])
                else []
            )
            if problem["code"] == "W_PROFILE_OVER_BUDGET":
                ids = sorted(
                    key
                    for key, p in pages.items()
                    if p["level"] == "must" and p["lifecycle"] == "active"
                )[:20]
            if not ids:
                continue
            if len(findings) >= self.models.config.heal.max_findings_per_run:
                return False
            try:
                context = {key: self.client.request("GET", "/pages/" + key) for key in ids}
            except WikiError as exc:
                if exc.status == 404:
                    continue
                raise
            fixes: list[Fix] = []
            if problem["code"] == "W_DEPENDS_ON_DEPRECATED":
                page = context[ids[0]]
                for rel in ("depends_on", "refines", "related"):
                    for target in page["relations"].get(rel, []):
                        if target in pages and pages[target]["lifecycle"] == "deprecated":
                            context[target] = self.client.request("GET", "/pages/" + target)
                            fixes.append(
                                Fix.model_validate(
                                    {
                                        "page": page["id"],
                                        "op": "remove_relation",
                                        "rel": rel,
                                        "target": target,
                                    }
                                )
                            )
            finding = self.writer.create(
                "lint_" + problem["code"],
                problem["message"],
                problem["message"],
                context,
                [{"page": p["id"], "quote": p["summary"]} for p in context.values()],
                fixes,
                job_id,
                str(problem.get("severity", "warning")),
            )
            if (
                finding["status"] == "open"
                and finding["id"] not in findings
                and finding["id"] not in self.existing
            ):
                findings.append(finding["id"])
        for profile in self.client.request("GET", "/profiles"):
            scoped = [
                p
                for p in pages.values()
                if p["lifecycle"] == "active"
                and ("*" in p["applies_to"] or set(p["applies_to"]) & set(profile["scopes"]))
            ]
            if scoped and not any(p["category"] == "errors" for p in scoped):
                if len(findings) >= self.models.config.heal.max_findings_per_run:
                    return False
                page = self.client.request(
                    "GET", "/pages/" + min(scoped, key=lambda p: p["id"])["id"]
                )
                finding = self.writer.create(
                    "coverage_errors",
                    "Нет правил обработки ошибок для " + profile["id"],
                    "Проверьте покрытие категории errors профиля.",
                    {page["id"]: page},
                    [{"page": page["id"], "quote": page["summary"]}],
                    [],
                    job_id,
                    "info",
                )
                if (
                    finding["status"] == "open"
                    and finding["id"] not in findings
                    and finding["id"] not in self.existing
                ):
                    findings.append(finding["id"])
        return True
