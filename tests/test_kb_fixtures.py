"""Stage 1 acceptance of the knowledge layer corpus (NFR-kb-stage-acceptance, FMT-wikisvc-core.kb-eval).

Hand-written io_uring / tokio / Rust-naming corpus in tests/fixtures/kb, the eval questions in
tests/fixtures/kb-eval.yaml and the labelled pairs in tests/fixtures/kb-pairs.yaml.
"""

from collections import Counter
from pathlib import Path

import pytest

from wikisvc.domain.markdown import citations, load_yaml
from wikisvc.domain.models import Page, RelationRef
from wikisvc.domain.registry import Registry
from wikisvc.domain.validate import parse_page, validate_set

pytestmark = pytest.mark.eval

FIXTURES = Path(__file__).parent / "fixtures"
CORPUS = FIXTURES / "kb"
MIN_PAGES = {"topic": 8, "tech": 3, "question": 2, "source": 1}
MIN_FACTS, MIN_QUESTIONS, MIN_MULTI, PAIRS, MIN_PER_LABEL = 50, 50, 15, 100, 15
LABELS = {"duplicate", "refines", "contradicts", "independent"}
NOTES = {"version-superseded", "related"}
STRONG = ("refines", "contradicts", "replaces")


@pytest.fixture(scope="module")
def corpus() -> list[Page]:
    files = sorted(CORPUS.rglob("*.md"))
    assert files, "corpus is empty"
    return [
        parse_page(path.read_text(encoding="utf-8"), path.relative_to(CORPUS).as_posix())
        for path in files
    ]


@pytest.fixture(scope="module")
def facts(corpus: list[Page]) -> dict[str, Page]:
    return {page.id: page for page in corpus if page.frontmatter.type == "fact"}


def load_list(name: str) -> list[dict[str, object]]:
    data = load_yaml((FIXTURES / name).read_text(encoding="utf-8"))
    assert isinstance(data, list) and all(isinstance(item, dict) for item in data), name
    return data


def ref_id(ref: str | RelationRef) -> str:
    return ref if isinstance(ref, str) else ref.id


def relation_edges(facts: dict[str, Page]) -> set[tuple[str, str, str]]:
    """(src, rel, dst) for every frontmatter relation of every fact, as declared (directed)."""
    return {
        (page.id, rel, ref_id(target))
        for page in facts.values()
        for rel, targets in page.frontmatter.relations.items()
        for target in targets
    }


def test_corpus_has_no_errors(corpus: list[Page], registry: Registry) -> None:
    issues = validate_set(corpus, registry)
    errors = sorted(f"{i.page}: {i.code} {i.message}" for i in issues if i.severity == "error")
    assert not errors, "\n".join(errors)


def test_corpus_page_counts(corpus: list[Page], facts: dict[str, Page]) -> None:
    counts = Counter(page.frontmatter.type for page in corpus)
    assert len(facts) >= MIN_FACTS, counts
    short = {kind: counts[kind] for kind, least in MIN_PAGES.items() if counts[kind] < least}
    assert not short, counts


def test_every_fact_has_hub_and_most_have_quotes(
    corpus: list[Page], facts: dict[str, Page]
) -> None:
    topics = {page.id for page in corpus if page.frontmatter.type == "topic"}
    without_hub = [
        fid for fid, page in facts.items() if not page.frontmatter.relations.get("about")
    ]
    assert not without_hub, without_hub
    without_source = [fid for fid, page in facts.items() if not page.frontmatter.sources]
    assert not without_source, without_source
    # Canonical facts hang off a topic hub. Variant facts of kb-pairs.yaml (restatements,
    # superseded kernel facts, misconceptions) hang off a tech page only; the quote share is
    # measured on the canonical set.
    canonical = {
        fid
        for fid, page in facts.items()
        if any(ref_id(ref) in topics for ref in page.frontmatter.relations["about"])
    }
    assert len(canonical) >= MIN_FACTS, len(canonical)
    quoted = [fid for fid in canonical if any(c.quote for c in citations(facts[fid].body_md))]
    assert len(quoted) >= 0.9 * len(canonical), f"{len(quoted)} of {len(canonical)} carry a quote"


def test_eval_set_shape_and_gold_ids(facts: dict[str, Page]) -> None:
    items = load_list("kb-eval.yaml")
    assert len(items) >= MIN_QUESTIONS, len(items)
    langs: Counter[str] = Counter()
    hops: Counter[str] = Counter()
    for item in items:
        assert set(item) == {"q", "lang", "hops", "gold"}, item
        assert isinstance(item["q"], str) and item["q"].strip(), item
        assert item["lang"] in ("en", "ru") and item["hops"] in ("single", "multi"), item
        gold = item["gold"]
        assert isinstance(gold, list) and gold and set(gold) <= facts.keys(), item
        assert item["hops"] == "single" or len(gold) >= 2, item
        langs[str(item["lang"])] += 1
        hops[str(item["hops"])] += 1
    assert langs["ru"] >= len(items) / 2 and langs["en"] >= 1, langs
    assert hops["multi"] >= MIN_MULTI and hops["single"] >= 1, hops


def test_pairs_labels_ids_and_edges(facts: dict[str, Page]) -> None:
    items = load_list("kb-pairs.yaml")
    assert len(items) == PAIRS, len(items)
    edges = relation_edges(facts)
    seen: set[frozenset[str]] = set()
    labels: Counter[str] = Counter()
    for item in items:
        assert set(item) <= {"a", "b", "label", "note"} and {"a", "b", "label"} <= set(item), item
        a, b, label = str(item["a"]), str(item["b"]), str(item["label"])
        note = item.get("note")
        assert a in facts and b in facts and a != b, item
        assert label in LABELS and (note is None or note in NOTES), item
        assert frozenset((a, b)) not in seen, item
        seen.add(frozenset((a, b)))
        labels[label] += 1
        forward = {rel for src, rel, dst in edges if (src, dst) == (a, b)}
        backward = {rel for src, rel, dst in edges if (src, dst) == (b, a)}
        either = forward | backward
        if label == "refines":
            assert "refines" in forward, item  # a refines b, never the other way round
        elif label == "contradicts":
            assert "contradicts" in either, item  # symmetric relation, declared on one side
            contested = (facts[a].frontmatter.model_extra or {}).get("confidence")
            assert contested == "contested", item  # the side that declares the contradiction
        elif label == "duplicate":
            assert not either, item
        elif note == "version-superseded":
            assert "replaces" in backward, item  # b (current) replaces a (superseded)
            assert not either & {"refines", "contradicts"}, item
        else:
            assert not either & set(STRONG), item
            assert note != "related" or "related" in either, item
    assert all(labels[label] >= MIN_PER_LABEL for label in LABELS), labels
