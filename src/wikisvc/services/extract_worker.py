"""Disposable document parser. Limits are installed before importing parser libraries."""

import resource
import sys
from collections.abc import Iterable
from pathlib import Path


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
    except ImportError:
        return 2
    except Exception:  # noqa: BLE001 -- isolate all parser failures in the disposable worker
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
