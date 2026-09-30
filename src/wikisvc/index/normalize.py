import re

import Stemmer


def normalize(text: str) -> str:
    ru, en = Stemmer.Stemmer("russian"), Stemmer.Stemmer("english")
    words = re.findall(r"\w+", text.lower().replace("ё", "е"))
    # Fold visual lookalikes in identifiers (1С/1C, 1СERP), never ordinary Russian words.
    lookalikes = str.maketrans("авекмнорстух", "abekmhopctyx")
    words = [word.translate(lookalikes) if re.search(r"[0-9a-z]", word) else word for word in words]
    return " ".join(str((ru if re.search("[а-я]", word) else en).stemWord(word)) for word in words)


def match_query(query: str) -> str:
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
            words = normalized.split()
            terms.extend(
                '"' + value + '"' + ("*" if raw.endswith("*") and pos == len(words) - 1 else "")
                for pos, value in enumerate(words)
            )
    return " AND ".join(terms)
