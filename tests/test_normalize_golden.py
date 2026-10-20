import json
from pathlib import Path

from wikisvc.index.normalize import expand_synonyms, match_query, normalize, normalize_many

GOLDEN = json.loads((Path(__file__).parent / "golden" / "normalize_golden.json").read_text())
SYNONYMS = [["выгрузка", "экспорт", "export"], ["счёт", "invoice"], ["1С", "1C", "ERP"]]


# Golden output was captured on the pre-optimisation implementation (ТЗ §11.1: behaviour unchanged).
def test_normalize_matches_golden() -> None:
    for text, expected in GOLDEN["normalize"]:
        assert normalize(text) == expected


def test_normalize_many_matches_normalize() -> None:
    texts = [text for text, _ in GOLDEN["normalize"]]
    assert normalize_many(texts) == [expected for _, expected in GOLDEN["normalize"]]
    assert normalize_many([]) == []


def test_expand_synonyms_matches_golden() -> None:
    for text, expected in GOLDEN["expand"]:
        assert expand_synonyms(normalize(text), SYNONYMS) == expected


def test_match_query_matches_golden() -> None:
    for query, operator, with_synonyms, without in GOLDEN["queries"]:
        assert match_query(query, SYNONYMS, operator) == with_synonyms
        assert match_query(query, None, operator) == without


def test_expand_synonyms_sees_in_place_edits() -> None:
    groups = [["alpha", "beta"]]
    assert expand_synonyms("alpha", groups) == "alpha beta"
    groups.append(["gamma", "alpha"])
    assert expand_synonyms("alpha", groups) == "alpha beta gamma"
    assert expand_synonyms("alpha", []) == "alpha"


def test_synonym_cache_is_bounded() -> None:
    for i in range(12):
        assert expand_synonyms("w", [[f"w{i}", "w"]]) == f"w w{i}"
