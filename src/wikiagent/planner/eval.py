import json
import time
from functools import partial
from pathlib import Path
from typing import Any

from wikiagent.chat.router import Intent
from wikiagent.config import AgentConfig
from wikiagent.models import PROMPT_VERSION, ModelClient
from wikiagent.planner.claims import Claims
from wikiagent.planner.classify import Classification, Relation, verify
from wikiagent.planner.plan import plan_changes
from wikiagent.state import AgentState
from wikisvc.domain.errors import WikiError
from wikisvc.domain.markdown import load_yaml


def scenario_actions(
    client: ModelClient, scenario: dict[str, Any], role: str
) -> tuple[list[str], list[str]]:
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
            {
                "message": scenario["input"],
                "scopes": scenario["scopes"],
                "previous_plan": scenario.get("previous_plan"),
                "profile_scopes": scenario.get("profile_scopes", []),
            },
        )
        for claim in claims.claims:
            result = (
                client.structured(
                    role,
                    "classify",
                    Classification,
                    {
                        "claim": claim.model_dump(),
                        "pages": list(pages.values()),
                        "message": scenario["input"],
                        "previous_plan": scenario.get("previous_plan"),
                    },
                    partial(verify, pages=pages),
                )
                if pages
                else Classification(
                    relations=[Relation(relation="new", confidence=1, reason="Нет похожих страниц")]
                )
            )
            plan = plan_changes(
                claim, result, pages, scenario.get("profile_scopes", []), scenario["scopes"]
            )
            items.extend(i["action"] for i in plan["items"])
            questions.extend(q["id"].split("-")[0] for q in plan["questions"])
    elif intent.intent == "cancel":
        items = ["cancel"]
    return items, questions


def evaluate_scenarios(
    config: AgentConfig,
    directory: Path,
    role: str = "planner",
    model: str | None = None,
    client: ModelClient | None = None,
    out: Path | None = None,
) -> dict[str, Any]:
    if role not in config.models:
        raise ValueError("Unknown model role")
    config = config.model_copy(deep=True)
    if model:
        config.models[role].model = model
    client = client or ModelClient(config, AgentState(config.state_dir))
    correct = extra_questions = false_conflicts = 0
    details: list[dict[str, Any]] = []
    paths = sorted(directory.glob("*.yaml"))
    report: dict[str, Any] = {
        "scenarios": len(paths),
        "models": {r: m.model for r, m in config.models.items()},
        "prompt_version": PROMPT_VERSION,
        "production_ready": False,
        "results": details,
    }
    started = time.monotonic()
    for path in paths:
        scenario = load_yaml(path.read_text())
        calls_before = client.calls
        case_start = time.monotonic()
        error = None
        items: list[str] = []
        questions: list[str] = []
        try:
            items, questions = scenario_actions(client, scenario, role)
        except WikiError as exc:
            error = exc.code
        expected = scenario["expected"]
        success = (
            error is None
            and sorted(items) == sorted(expected["actions"])
            and sorted(questions) == sorted(expected["questions"])
        )
        correct += int(success)
        false_conflicts += max(
            0, questions.count("conflict") - expected["questions"].count("conflict")
        )
        extra_questions += max(0, len(questions) - len(expected["questions"]))
        details.append(
            {
                "scenario": path.stem,
                "pass": success,
                "actions": items,
                "questions": questions,
                "error": error,
                "model_calls": client.calls - calls_before,
                "seconds": round(time.monotonic() - case_start, 2),
            }
        )
        report.update(
            completed=len(details),
            accuracy=correct / max(len(paths), 1),
            false_conflicts=false_conflicts,
            extra_questions_per_scenario=extra_questions / max(len(paths), 1),
            forbidden_attempts=client.forbidden_attempts,
            seconds=round(time.monotonic() - started, 2),
        )
        report["production_ready"] = (
            len(details) == len(paths)
            and len(paths) >= 30
            and report["accuracy"] >= 0.9
            and client.forbidden_attempts == 0
            and report["extra_questions_per_scenario"] <= 1
        )
        if out:
            out.parent.mkdir(parents=True, exist_ok=True)
            temporary = out.with_suffix(out.suffix + ".tmp")
            temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
            temporary.replace(out)
    return report
