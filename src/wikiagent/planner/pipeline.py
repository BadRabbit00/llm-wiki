from functools import partial
from typing import Any

from wikiagent.client import WikiClient
from wikiagent.models import ModelClient
from wikiagent.planner.builder import Builder
from wikiagent.planner.claims import Claims
from wikiagent.planner.classify import Classification, verify
from wikiagent.planner.plan import plan_changes
from wikiagent.planner.related import collect


class Planner:
    def __init__(self, client: WikiClient, models: ModelClient) -> None:
        self.client, self.models = client, models
        self.builder = Builder(client, models)

    def run(
        self,
        text: str,
        session: dict[str, Any],
        transcript: str,
        bound: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        vocabulary = self.client.request("GET", "/scopes")
        profiles = self.client.request("GET", "/profiles")
        scopes: list[str] = next(
            (p["scopes"] for p in profiles if p["id"] == session.get("profile")), []
        )
        claims = self.models.structured(
            "planner",
            "extract_claims",
            Claims,
            {
                "message": text,
                "previous_plan": session.get("plan"),
                "context": bound,
                "scopes": vocabulary,
                "profile_scopes": scopes,
            },
        )
        if claims.remove_ids:
            from wikisvc.domain.errors import WikiError

            previous = session.get("plan") or {}
            allowed = {i["id"] for i in previous.get("accept_body", {}).get("promote", [])}
            if set(claims.remove_ids) - allowed:
                raise WikiError(
                    "E_AGENT_REPAIR", "Удалять можно только новые кандидаты текущего плана."
                )
            for page_id in claims.remove_ids:
                self.client.request("DELETE", f"/proposals/{previous['proposal']}/pages/{page_id}")
            previous["accept_body"]["promote"] = [
                i for i in previous["accept_body"]["promote"] if i["id"] not in claims.remove_ids
            ]
            retired = {
                d["id"]
                for item in previous.get("items", [])
                if item.get("target") in claims.remove_ids
                for d in item.get("deprecate", [])
            }
            previous["accept_body"]["deprecate"] = [
                d for d in previous["accept_body"].get("deprecate", []) if d["id"] not in retired
            ]
        plans: list[dict[str, Any]] = []
        current: dict[str, Any] = {"items": [], "questions": [], "assumptions": []}
        for claim in claims.claims:
            pages = collect(self.client, claim) if claim.kind == "rule" else {}
            classified = (
                self.models.structured(
                    "planner",
                    "classify",
                    Classification,
                    {
                        "claim": claim.model_dump(),
                        "pages": list(pages.values()),
                        "message": text,
                        "previous_plan": session.get("plan"),
                    },
                    partial(verify, pages=pages),
                )
                if pages
                else Classification.model_validate(
                    {
                        "relations": [
                            {
                                "relation": "new",
                                "confidence": 1,
                                "reason": "Похожих правил не найдено.",
                            }
                        ]
                    }
                )
            )
            part = plan_changes(claim, classified, pages, scopes, vocabulary)
            if len(current["items"]) + len(part["items"]) > 10 and current["items"]:
                plans.append(
                    self.builder.build(
                        current, session if not plans else {**session, "plan": None}, transcript
                    )
                )
                current = {"items": [], "questions": [], "assumptions": []}
            # Extra affected pages remain in impact notes, never cause more than ten plan items.
            current["items"].extend(part["items"][: 10 - len(current["items"])])
            current["touches_must"] = current.get("touches_must", False) or part.get(
                "touches_must", False
            )
            current["questions"].extend(part["questions"])
            current["assumptions"].extend(part["assumptions"])
        current["questions"] = current["questions"][:3]
        current["assumptions"] = list(dict.fromkeys(current["assumptions"]))
        for n, item in enumerate(current["items"], 1):
            item["n"] = n
        plans.append(
            self.builder.build(
                current, session if not plans else {**session, "plan": None}, transcript
            )
        )
        return plans
