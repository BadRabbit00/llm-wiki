import pytest
from fake_llm import claim

from wikiagent.jobs.ingest_book import Candidate
from wikiagent.models import strict_schema
from wikiagent.planner.builder import examples_md
from wikiagent.planner.claims import Claim, StrictModel
from wikiagent.planner.classify import Classification
from wikiagent.planner.plan import plan_changes

DISCLAIMER = "Примеры предложены моделью, проверьте."
PARTIAL = "Примеры неполные: добавьте недостающие до принятия."


@pytest.mark.parametrize(
    ("good", "bad", "expected"),
    [
        (
            " await client.get(url)\n",
            "requests.get(url)",
            DISCLAIMER + "\n\nТак:\n\nawait client.get(url)\n\nНе так:\n\nrequests.get(url)",
        ),
        ("await client.get(url)", " \n", DISCLAIMER + "\n\nТак:\n\nawait client.get(url)"),
        ("", "requests.get(url)", DISCLAIMER + "\n\nНе так:\n\nrequests.get(url)"),
        (" ", "\n\t", "Примеров нет: модель их не предложила. Добавьте до принятия."),
    ],
    ids=["both", "only-good", "only-bad", "none"],
)
def test_examples_section_shows_only_given_examples(good: str, bad: str, expected: str) -> None:
    assert examples_md(good, bad) == expected


@pytest.mark.parametrize(
    ("good", "bad", "expected"),
    [
        ("await client.get(url)", "requests.get(url)", DISCLAIMER),
        ("await client.get(url)", "", PARTIAL),
        ("", "requests.get(url)", PARTIAL),
        (" ", "\n", PARTIAL),
    ],
    ids=["both", "only-good", "only-bad", "blank"],
)
def test_plan_assumes_examples_only_when_both_given(good: str, bad: str, expected: str) -> None:
    classified = Classification.model_validate(
        {"relations": [{"relation": "new", "confidence": 1, "reason": "Нет совпадений."}]}
    )
    plan = plan_changes(
        Claim.model_validate(claim(good_example=good, bad_example=bad)),
        classified,
        {},
        ["lang:python"],
        ["lang:python"],
    )
    assert [a for a in plan["assumptions"] if a in (DISCLAIMER, PARTIAL)] == [expected]


def schema_keys(value: object) -> set[str]:
    if isinstance(value, list):
        return set().union(*(schema_keys(item) for item in value))
    if not isinstance(value, dict):
        return set()
    return set(value).union(*(schema_keys(item) for item in value.values()))


@pytest.mark.parametrize("model", [Claim, Candidate], ids=["chat", "book"])
def test_model_schema_requires_examples_but_cannot_bound_them(model: type[StrictModel]) -> None:
    # The grammar forces both fields to appear, yet admits "": the gap behind issue #8.
    schema = strict_schema(model.model_json_schema())
    assert {"good_example", "bad_example"} <= set(schema["required"])
    assert schema["required"] == list(schema["properties"])
    assert schema["additionalProperties"] is False
    bounds = {"default", "minLength", "maxLength", "minItems", "maxItems", "minimum", "maximum"}
    assert not schema_keys(schema) & bounds
