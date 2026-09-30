import math
import re
from collections import Counter


def secret_kinds(text: str, entropy_threshold: float = 4.5) -> list[str]:
    patterns = {
        "private_key": r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----",
        "aws": r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b",
        "github": r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b|\bgithub_pat_[A-Za-z0-9_]{20,}",
        "slack": r"\bxox[baprs]-[A-Za-z0-9-]{10,}",
        "jwt": r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}",
    }
    found = [name for name, pattern in patterns.items() if re.search(pattern, text)]
    # Recognize only explicit documentation placeholders, never arbitrary <credentials>.
    placeholder = r"\$\{[A-Za-z_][A-Za-z0-9_]*\}|<(?:secret|password|token|api[_-]?key|секрет|пароль|токен|redacted|REPLACE_ME)>"
    safe_text = re.sub(placeholder, "", text, flags=re.IGNORECASE)
    contextual = {
        "assignment": r"""(?i)\b(?:password|passwd|secret|token|api[_-]?key)["']?[ \t]*[:=][ \t]*["'<]*[^\s"'<>]{8,}""",
        "url_password": r"\b[A-Za-z][A-Za-z0-9+.-]*://[^\s/:@]+:[^\s/@]+@",
        "bearer": r"(?i)\bBearer[ \t]+[<\"']*[A-Za-z0-9._~+/-]{8,}=*",
    }
    found.extend(name for name, pattern in contextual.items() if re.search(pattern, safe_text))
    text = re.sub(r"<[^>\n]+>|\$\{[^}\n]+\}", "", text)
    for match in re.finditer(r"(?<![\w/])[A-Za-z0-9+/=_-]{32,}(?!\w)", text):
        value = match[0]
        if len(value) in (32, 40, 64) and re.fullmatch(r"[0-9a-fA-F]+", value):
            continue  # ordinary MD5/Git/SHA-256 identifiers; context checks above still apply
        if not any(c.isdigit() for c in value) or len(set(value)) < 10:
            continue
        entropy = -sum(
            (count / len(value)) * math.log2(count / len(value))
            for count in Counter(value).values()
        )
        threshold = (
            min(entropy_threshold, 3.5)
            if re.fullmatch("[0-9a-fA-F]+", value)
            else entropy_threshold
        )
        if entropy >= threshold:
            found.append("high_entropy")
            break
    return found
