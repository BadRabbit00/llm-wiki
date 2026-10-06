from typing import Any, Literal

from pydantic import Field

from wikiagent.planner.claims import StrictModel
from wikiagent.planner.classify import evidence_in
from wikisvc.domain.errors import WikiError


class Evidence(StrictModel):
    page: str
    quote: str = Field(min_length=1, max_length=4000)


class Fix(StrictModel):
    page: str = Field(pattern=r"^[a-z]+-[a-z0-9-]+$")
    op: Literal["set_field", "add_relation", "remove_relation", "append_to_section"]
    field: Literal["summary", "applies_to", "aliases", "category"] | None = None
    value: str | list[str] | None = None
    rel: Literal["refines", "conflicts_with", "supersedes", "depends_on", "related"] | None = None
    target: str | None = None
    heading: str | None = None
    text: str | None = None


class Verdict(StrictModel):
    relation: Literal["none", "duplicate", "refines", "conflicts", "scope_mismatch"]
    confidence: float = Field(ge=0, le=1)
    explanation: str = Field(max_length=4000)
    evidence: list[Evidence] = Field(default_factory=list, max_length=10)
    suggested_fix: list[Fix] = Field(default_factory=list, max_length=10)


def validate_verdict(verdict: Verdict, pages: dict[str, dict[str, Any]]) -> None:
    if verdict.relation != "none" and not verdict.evidence:
        raise WikiError("E_QUOTE_NOT_FOUND", "Для находки нужны цитаты.")
    for evidence in verdict.evidence:
        if evidence.page not in pages or not evidence_in(evidence.quote, pages[evidence.page]):
            raise WikiError("E_QUOTE_NOT_FOUND", "Цитата лекаря не найдена в страницах.")
    for fix in verdict.suggested_fix:
        if fix.page not in pages or (fix.target is not None and fix.target not in pages):
            raise WikiError(
                "E_AGENT_TOOL_FORBIDDEN", "Исправление ограничено проверяемыми страницами."
            )
        if fix.op == "set_field" and (fix.field is None or fix.value is None):
            raise WikiError("E_MODEL_OUTPUT", "Нужны field и value.")
        if fix.op in ("add_relation", "remove_relation") and (
            not fix.rel or not fix.target or fix.target == fix.page
        ):
            raise WikiError("E_MODEL_OUTPUT", "Нужна связь с другой страницей пары.")
        if fix.op == "append_to_section" and (not fix.heading or not fix.text):
            raise WikiError("E_MODEL_OUTPUT", "Нужны раздел и текст исправления.")
