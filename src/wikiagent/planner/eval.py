from functools import partial
from pathlib import Path
from typing import Any

from wikiagent.chat.router import Intent
from wikiagent.config import AgentConfig
from wikiagent.models import ModelClient
from wikiagent.planner.claims import Claims
from wikiagent.planner.classify import Classification, Relation, verify
from wikiagent.planner.plan import plan_changes
from wikiagent.state import AgentState
from wikisvc.domain.markdown import load_yaml


def evaluate_scenarios(
    config: AgentConfig,
    directory: Path,
    role: str = "planner",
    model: str | None = None,
    client: ModelClient | None = None,
) -> dict[str, Any]:
    if role not in config.models:
        raise ValueError("Unknown model role")
    config = config.model_copy(deep=True)
    if model:
        config.models[role].model = model
    client = client or ModelClient(config, AgentState(config.state_dir))
    total = correct = extra_questions = false_conflicts = forbidden = 0
    details = []
    for path in sorted(directory.glob("*.yaml")):
        scenario = load_yaml(path.read_text())
        pages = {p["id"]: p for p in scenario["initial_pages"]}
        intent = client.structured(
            "chat",
            "route",
            Intent,
            {"message": scenario["input"], "plan": scenario.get("previous_plan")},
        )
        items: list[str] = []
        questions: list[str] = []
        if intent.intent in ("intake", "edit"):
            claims = client.structured(
                role,
                "extract_claims",
                Claims,
                {"message": scenario["input"], "scopes": scenario["scopes"]},
            )
            for claim in claims.claims:
                result = (
                    client.structured(
                        role,
                        "classify",
                        Classification,
                        {"claim": claim.model_dump(), "pages": list(pages.values())},
                        partial(verify, pages=pages),
                    )
                    if pages
                    else Classification(
                        relations=[
                            Relation(relation="new", confidence=1, reason="Нет похожих страниц")
                        ]
                    )
                )
                plan = plan_changes(
                    claim, result, pages, scenario.get("profile_scopes", []), scenario["scopes"]
                )
                items.extend(i["action"] for i in plan["items"])
                questions.extend(q["id"].split("-")[0] for q in plan["questions"])
        elif intent.intent == "cancel":
            items = ["cancel"]
        expected = scenario["expected"]
        success = sorted(items) == sorted(expected["actions"]) and sorted(questions) == sorted(
            expected["questions"]
        )
        correct += int(success)
        total += 1
        false_conflicts += max(
            0, questions.count("conflict") - expected["questions"].count("conflict")
        )
        extra_questions += max(0, len(questions) - len(expected["questions"]))
        details.append(
            {"scenario": path.stem, "pass": success, "actions": items, "questions": questions}
        )
    forbidden = client.forbidden_attempts
    accuracy = correct / total if total else 0
    return {
        "scenarios": total,
        "accuracy": accuracy,
        "false_conflicts": false_conflicts,
        "extra_questions_per_scenario": extra_questions / max(total, 1),
        "forbidden_attempts": forbidden,
        "production_ready": total >= 30
        and accuracy >= 0.9
        and forbidden == 0
        and extra_questions / max(total, 1) <= 1,
        "results": details,
    }
