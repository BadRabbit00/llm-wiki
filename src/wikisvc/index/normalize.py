import re
from functools import lru_cache
from pathlib import Path

import Stemmer


def normalize(text: str) -> str:
    ru, en = Stemmer.Stemmer("russian"), Stemmer.Stemmer("english")
    words = re.findall(r"\w+", text.lower().replace("ё", "е"))
    # Fold visual lookalikes in identifiers (1С/1C, 1СERP), never ordinary Russian words.
    lookalikes = str.maketrans("авекмнорстух", "abekmhopctyx")
    words = [word.translate(lookalikes) if re.search(r"[0-9a-z]", word) else word for word in words]
    return " ".join(str((ru if re.search("[а-я]", word) else en).stemWord(word)) for word in words)


@lru_cache(maxsize=1)
def stopwords() -> set[str]:
    return set(normalize(Path(__file__).with_name("stopwords.txt").read_text()).split())


def expand_synonyms(text: str, synonyms: list[list[str]]) -> str:
    words = set(text.split())
    additions = set()
    for group in synonyms:
        normalized = {normalize(value) for value in group}
        if words & normalized:
            additions.update(normalized - words)
    return text + (" " + " ".join(sorted(additions)) if additions else "")


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
