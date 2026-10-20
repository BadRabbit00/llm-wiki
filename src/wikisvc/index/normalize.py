import re
import threading
from functools import lru_cache
from pathlib import Path

import Stemmer

_WORD = re.compile(r"\w+")
_HAS_LATIN_OR_DIGIT = re.compile(r"[0-9a-z]")
_HAS_CYRILLIC = re.compile(r"[а-я]")
# Fold visual lookalikes in identifiers (1С/1C, 1СERP), never ordinary Russian words.
_LOOKALIKES = str.maketrans("авекмнорстух", "abekmhopctyx")

# PyStemmer objects are not safe to share between threads: one pair per thread.
_local = threading.local()


def _stemmers() -> tuple[Stemmer.Stemmer, Stemmer.Stemmer]:
    pair: tuple[Stemmer.Stemmer, Stemmer.Stemmer] | None = getattr(_local, "pair", None)
    if pair is None:
        pair = (Stemmer.Stemmer("russian"), Stemmer.Stemmer("english"))
        _local.pair = pair
    return pair


@lru_cache(maxsize=65536)
def _stem_word(word: str) -> str:
    # Words repeat heavily across a wiki, so the pure word -> stem mapping is memoised.
    if _HAS_LATIN_OR_DIGIT.search(word):
        word = word.translate(_LOOKALIKES)
    ru, en = _stemmers()
    return str((ru if _HAS_CYRILLIC.search(word) else en).stemWord(word))


def normalize(text: str) -> str:
    return " ".join(_stem_word(word) for word in _WORD.findall(text.lower().replace("ё", "е")))


# doc: CLS-wikisvc-core.normalize_many
def normalize_many(texts: list[str]) -> list[str]:
    return [normalize(text) for text in texts]


@lru_cache(maxsize=1)
def stopwords() -> set[str]:
    return set(normalize(Path(__file__).with_name("stopwords.txt").read_text()).split())


_SynonymIndex = dict[str, frozenset[frozenset[str]]]
# id(list) -> (the list itself, its length, index). The registry builds the list once per load;
# identity plus length is O(1) per call and still sees appended groups and a reused id.
_synonym_cache: dict[int, tuple[list[list[str]], int, _SynonymIndex]] = {}
_SYNONYM_CACHE_LIMIT = 8
_synonym_lock = threading.Lock()


def _synonym_index(synonyms: list[list[str]]) -> _SynonymIndex:
    size = len(synonyms)
    with _synonym_lock:
        hit = _synonym_cache.get(id(synonyms))
        if hit is not None and hit[0] is synonyms and hit[1] == size:
            return hit[2]
    by_word: dict[str, set[frozenset[str]]] = {}
    for group in synonyms:
        normalized = frozenset(normalize(value) for value in group)
        for word in normalized:
            by_word.setdefault(word, set()).add(normalized)
    index = {word: frozenset(groups) for word, groups in by_word.items()}
    with _synonym_lock:
        if len(_synonym_cache) >= _SYNONYM_CACHE_LIMIT:
            _synonym_cache.pop(next(iter(_synonym_cache)))
        _synonym_cache[id(synonyms)] = (synonyms, size, index)
    return index


def expand_synonyms(text: str, synonyms: list[list[str]]) -> str:
    words = set(text.split())
    if not synonyms:
        return text
    index = _synonym_index(synonyms)
    groups = {group for word in words if word in index for group in index[word]}
    additions = set().union(*groups) - words if groups else set()
    return text + (" " + " ".join(sorted(additions)) if additions else "")


# doc: CLS-wikisvc-core.match_query
def match_query(query: str, synonyms: list[list[str]] | None = None, operator: str = "AND") -> str:
    terms: list[str] = []
    for match in re.finditer(r'"([^"\n]+)"|(\S+)', query):
        phrase, word = match.groups()
        raw = phrase or word
        normalized = normalize(raw)
        if not normalized:
            continue
        if phrase:
            terms.append('"' + normalized + '"')
        else:
            words = [word for word in normalized.split() if word not in stopwords()]
            terms.extend(
                "("
                + " OR ".join(
                    '"'
                    + synonym
                    + '"'
                    + ("*" if raw.endswith("*") and pos == len(words) - 1 else "")
                    for synonym in expand_synonyms(value, synonyms or []).split()
                )
                + ")"
                if synonyms
                else '"'
                + value
                + '"'
                + ("*" if raw.endswith("*") and pos == len(words) - 1 else "")
                for pos, value in enumerate(words)
            )
    return (" OR " if operator == "OR" else " AND ").join(terms)
