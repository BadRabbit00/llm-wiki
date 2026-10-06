from typing import Any

from wikiagent.client import WikiClient
from wikiagent.heal.verdicts import Fix
from wikiagent.models import ModelClient
from wikiagent.planner.builder import Builder
from wikisvc.domain.errors import WikiError


class FindingWriter:
    def __init__(self, client: WikiClient, models: ModelClient) -> None:
        self.client, self.models = client, models
        self.builder = Builder(client, models)

    def create(
        self,
        kind: str,
        summary: str,
        explanation: str,
        pages: dict[str, dict[str, Any]],
        evidence: list[dict[str, str]],
        fixes: list[Fix],
        run_id: str,
        severity: str = "warning",
    ) -> dict[str, Any]:
        payload = {
            "kind": kind,
            "severity": severity,
            "pages": sorted(pages),
            "summary": summary[:500],
            "explanation": explanation,
            "evidence": evidence,
            "run_id": run_id,
        }
        finding: dict[str, Any] = self.client.request("POST", "/findings", json=payload)
        if finding["status"] != "open" or finding["proposal_pid"] or not fixes:
            return finding
        marker = "Finding " + finding["fingerprint"]
        pid = None
        for proposal in self.client.all("/proposals", kind="heal"):
            if marker in proposal["description"] and proposal["status"] in ("draft", "submitted"):
                pid = proposal["pid"]
                break
        if pid is None:
            pid = self.client.request(
                "POST",
                "/proposals",
                json={
                    "kind": "heal",
                    "title": ("Исправление: " + summary)[:200],
                    "description": self.builder.description(
                        marker
                        + "\n"
                        + explanation
                        + "\n"
                        + "\n".join(e["page"] + ": " + e["quote"] for e in evidence)
                    ),
                },
            )["pid"]
        proposal = self.client.request("GET", "/proposals/" + pid)
        if proposal["status"] == "draft":
            for fix in fixes:
                if fix.page not in pages:
                    raise WikiError(
                        "E_AGENT_TOOL_FORBIDDEN", "Правка страницы вне находки запрещена."
                    )
                op = fix.model_dump(exclude={"page"}, exclude_none=True)
                self.client.request(
                    "PATCH",
                    f"/proposals/{pid}/pages/{fix.page}",
                    json={"ops": [op], "base_version": pages[fix.page]["version"]},
                )
            validation = self.client.request("GET", f"/proposals/{pid}/validate")
            if validation["errors"]:
                raise WikiError(
                    "E_AGENT_VALIDATION",
                    "Исправление лекаря не прошло проверку.",
                    details=validation["errors"],
                )
            self.client.request(
                "PUT",
                f"/proposals/{pid}/notes",
                json={
                    "summary": summary,
                    "items": [f.model_dump() for f in fixes],
                    "questions": [],
                    "assumptions": [],
                    "impact": self.client.request("GET", f"/proposals/{pid}/impact"),
                    "needs_double_confirm": any(p.get("level") == "must" for p in pages.values()),
                },
            )
            self.client.request("POST", f"/proposals/{pid}/submit")
        result: dict[str, Any] = self.client.request(
            "POST", "/findings", json={**payload, "proposal_pid": pid}
        )
        return result
