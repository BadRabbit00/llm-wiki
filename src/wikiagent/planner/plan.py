from typing import Any

from wikiagent.planner.claims import Claim
from wikiagent.planner.classify import Classification


def plan_changes(
    claim: Claim,
    classified: Classification,
    pages: dict[str, dict[str, Any]],
    scopes: list[str],
    vocabulary: list[str],
) -> dict[str, Any]:
    """No model decisions or mutations in this step: turn evidence into a review plan."""
    if claim.kind == "not_rule":
        return {
            "items": [],
            "questions": [],
            "assumptions": ["Описание бизнес-процесса относится ко второму этапу."],
        }
    applies = scopes or claim.scopes_guess or ["*"]
    questions = []
    unknown = set(applies) - set(vocabulary) - {"*"}
    if unknown:
        questions.append(
            {
                "id": "scope-" + claim.id,
                "text": "Нужно добавить область: " + ", ".join(sorted(unknown)),
                "options": ["wikisvc scopes add " + scope for scope in sorted(unknown)],
            }
        )
        applies = ["*"]
    elif claim.ambiguous_scope:
        questions.append(
            {
                "id": "scope-" + claim.id,
                "text": "Для какой области действует правило?",
                "options": applies,
            }
        )
    if claim.level_guess == "must" and not claim.owner:
        questions.append(
            {
                "id": "owner-" + claim.id,
                "text": "Кто владелец обязательного правила?",
                "options": [],
            }
        )
    item: dict[str, Any] = {
        "action": "create_rule",
        "target": claim.id,
        "thesis": claim.thesis,
        "level": claim.level_guess,
        "owner": claim.owner,
        "scopes": applies,
        "reason": claim.rationale,
        "confidence": min(r.confidence for r in classified.relations),
        "claim": claim.model_dump(),
        "relations": {},
        "deprecate": [],
    }
    flags = []
    for relation in classified.relations:
        target = relation.target
        if relation.relation == "new" or not target:
            continue
        if relation.relation == "duplicate_of":
            item.update(action="noop_duplicate", target=target, reason=relation.reason)
        elif relation.relation == "extends_scope":
            item.update(
                action="patch_rule",
                target=target,
                scopes=sorted(set(pages[target]["applies_to"]) | set(applies)),
                reason=relation.reason,
            )
        elif relation.relation == "affects":
            flags.append(
                {
                    "action": "flag_page",
                    "target": target,
                    "reason": relation.reason,
                    "confidence": relation.confidence,
                }
            )
        else:
            item["relations"].setdefault(relation.relation, []).append(target)
            if relation.relation == "supersedes":
                item["action"] = "supersede_rule"
                item["deprecate"].append({"id": target, "reason": "Заменено " + claim.id})
            if relation.relation == "conflicts_with" and (
                pages[target].get("lifecycle") == "active" or pages[target].get("level") == "must"
            ):
                questions.append(
                    {
                        "id": "conflict-" + target,
                        "text": f"Правило {target} противоречит новому. Что сделать?",
                        "options": ["Заменить новым", "Развести области", "Не добавлять новое"],
                    }
                )
    return {
        "touches_must": any(
            pages[r.target].get("level") == "must"
            for r in classified.relations
            if r.target in pages
        ),
        "items": [item, *flags],
        "questions": questions,
        "assumptions": [
            "Области: " + ", ".join(applies),
            "Уровень: " + claim.level_guess,
            "Примеры предложены моделью, проверьте.",
        ],
    }
