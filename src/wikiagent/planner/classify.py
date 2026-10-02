from typing import Any, Literal

from pydantic import Field

from wikiagent.planner.claims import StrictModel
from wikisvc.domain.errors import WikiError


class Relation(StrictModel):
    relation: Literal[
        "new", "duplicate_of", "refines", "extends_scope", "conflicts_with", "supersedes", "affects"
    ]
    target: str | None = None
    confidence: float = Field(ge=0, le=1)
    quote: str = Field(default="", max_length=4000)
    reason: str = Field(min_length=1, max_length=4000)


class Classification(StrictModel):
    relations: list[Relation] = Field(min_length=1, max_length=20)


def evidence_in(quote: str, page: dict[str, Any]) -> bool:
    content = "\n".join(str(page.get(key, "")) for key in ("summary", "title", "body_md"))
    return bool(quote.strip()) and " ".join(quote.casefold().split()) in " ".join(
        content.casefold().split()
    )


def verify(result: Classification, pages: dict[str, dict[str, Any]]) -> None:
    for relation in result.relations:
        if relation.relation == "new":
            if relation.target is not None:
                raise WikiError("E_MODEL_OUTPUT", "new не должен ссылаться на страницу.")
            continue
        if (
            not relation.target
            or relation.target not in pages
            or not evidence_in(relation.quote, pages[relation.target])
        ):
            raise WikiError(
                "E_QUOTE_NOT_FOUND", "Цитата классификатора не найдена в полученной странице."
            )
        if relation.relation != "affects" and pages[relation.target]["type"] != "rule":
            raise WikiError("E_MODEL_OUTPUT", "Связь правил должна ссылаться на rule.")
