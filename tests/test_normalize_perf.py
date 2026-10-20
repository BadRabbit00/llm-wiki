import re
import time
from pathlib import Path

import pytest
import Stemmer

from wikisvc.index.normalize import _stem_word, expand_synonyms, normalize

pytestmark = pytest.mark.perf

FIXTURES = Path(__file__).parent / "fixtures" / "wiki"
SYNONYMS = [
    ["выгрузка", "экспорт", "export"],
    ["счёт", "invoice"],
    ["1С", "1C", "ERP"],
    ["банк", "bank"],
]
PASSES = 5
MIN_SPEEDUP = 3.0


def naive_normalize(text: str) -> str:
    """Reference implementation from before the optimisation (ТЗ §11.1)."""
    ru, en = Stemmer.Stemmer("russian"), Stemmer.Stemmer("english")
    words = re.findall(r"\w+", text.lower().replace("ё", "е"))
    lookalikes = str.maketrans("авекмнорстух", "abekmhopctyx")
    words = [word.translate(lookalikes) if re.search(r"[0-9a-z]", word) else word for word in words]
    return " ".join(str((ru if re.search("[а-я]", word) else en).stemWord(word)) for word in words)


def naive_expand(text: str, synonyms: list[list[str]]) -> str:
    words = set(text.split())
    additions: set[str] = set()
    for group in synonyms:
        normalized = {naive_normalize(value) for value in group}
        if words & normalized:
            additions.update(normalized - words)
    return text + (" " + " ".join(sorted(additions)) if additions else "")


def corpus() -> list[str]:
    return [path.read_text() for path in sorted(FIXTURES.rglob("*.md"))] * PASSES


def best_of(runs: int, func: object) -> float:
    assert callable(func)
    best = float("inf")
    for _ in range(runs):
        started = time.perf_counter()
        func()
        best = min(best, time.perf_counter() - started)
    return best


def test_indexing_normalization_is_at_least_3x_faster() -> None:
    texts = corpus()

    def old() -> list[str]:
        return [naive_expand(naive_normalize(text), SYNONYMS) for text in texts]

    def new() -> list[str]:
        _stem_word.cache_clear()  # cold start: the speedup must not depend on a warm cache
        return [expand_synonyms(normalize(text), SYNONYMS) for text in texts]

    assert old() == new()  # same behaviour first
    before, after = best_of(3, old), best_of(3, new)
    speedup = before / after
    print(
        f"normalize+expand over {len(texts)} texts: {before:.3f}s -> {after:.3f}s, x{speedup:.1f}"
    )
    assert speedup >= MIN_SPEEDUP
