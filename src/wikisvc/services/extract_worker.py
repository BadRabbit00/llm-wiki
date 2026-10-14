"""Disposable document parser. Limits are installed before importing parser libraries."""

import os
import resource
import sys
from collections.abc import Iterable
from pathlib import Path


def worker_env() -> dict[str, str]:
    # Nix glibc maps the whole locale-archive named by LOCALE_ARCHIVE* into memory at startup,
    # eating the RLIMIT_AS budget before the parser even runs. The parser needs no locale.
    env = {key: value for key, value in os.environ.items() if not key.startswith("LOCALE_ARCHIVE")}
    env["LC_ALL"] = "C.UTF-8"
    return env


def stderr_tail(data: bytes, lines: int = 20, limit: int = 2000) -> str:
    # The worker writes only the exception class and the missing module name to stderr (never
    # the message, which may quote the document), so the tail is safe for the journal.
    text = data.decode("utf-8", errors="replace").strip()
    return "\n".join(text.splitlines()[-lines:])[-limit:]


def extract(file: Path) -> Iterable[str]:
    if file.suffix.lower() == ".pdf":
        from pypdf import PdfReader

        for page in PdfReader(str(file)).pages:
            yield page.extract_text() or ""
    elif file.suffix.lower() == ".docx":
        from docx import Document

        for paragraph in Document(str(file)).paragraphs:
            yield paragraph.text
    else:
        raise ValueError("Unsupported format")


def main() -> int:
    file = Path(sys.argv[1])
    memory, maximum, seconds = map(int, sys.argv[2:5])
    resource.setrlimit(resource.RLIMIT_AS, (memory * 1024 * 1024, memory * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_CPU, (seconds, seconds))
    resource.setrlimit(resource.RLIMIT_FSIZE, (1024 * 1024, 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    try:
        if len(sys.argv) > 5 and sys.argv[5] == "--pages":
            import json

            from wikisvc.services.document_pages import batch

            result = batch(file, int(sys.argv[6]), int(sys.argv[7]))
            output = json.dumps(result, ensure_ascii=False)
            if len(output) > maximum:
                return 3
            sys.stdout.buffer.write(output.encode("utf-8"))
            return 0
        parts: list[str] = []
        length = 0
        for part in extract(file):
            length += len(part) + 2
            if length > maximum:
                return 3
            parts.append(part)
        sys.stdout.buffer.write("\n\n".join(parts).encode("utf-8"))
    except ImportError as exc:
        sys.stderr.write(f"ImportError: module {exc.name or 'unknown'} is not available\n")
        return 2
    except MemoryError:  # RLIMIT_AS exhausted: a resource limit, not a malformed document
        sys.stderr.write("MemoryError: address-space limit reached\n")
        return 4
    except Exception as exc:  # noqa: BLE001 -- isolate all parser failures in the disposable worker
        sys.stderr.write(f"{type(exc).__module__}.{type(exc).__qualname__} in the parser\n")
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
