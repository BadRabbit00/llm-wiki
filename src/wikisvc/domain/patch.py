from copy import deepcopy
from typing import Any

from wikisvc.domain.errors import WikiError
from wikisvc.domain.markdown import sections


def section_span(body: str, heading: str) -> tuple[int, int, int, int]:
    parts = sections(body)
    matches = [(i, part) for i, part in enumerate(parts) if part.heading == heading]
    if len(matches) != 1:
        raise WikiError(
            "E_PATCH_SECTION",
            f"Раздел '{heading}' отсутствует или неоднозначен.",
            "Укажите уникальное название раздела.",
        )
    index, part = matches[0]
    end = next(
        (candidate.start for candidate in parts[index + 1 :] if candidate.level <= part.level),
        len(body),
    )
    return part.start, part.body_start, end, part.level


def apply_patch(
    metadata: dict[str, Any], body: str, ops: list[dict[str, Any]]
) -> tuple[dict[str, Any], str]:
    result = deepcopy(metadata)
    if not ops or len(ops) > 100:
        raise WikiError("E_PATCH_INVALID", "Нужно от 1 до 100 операций.")
    try:
        for operation in ops:
            op = operation["op"]
            if op == "set_field":
                field = operation["field"]
                if field in ("verified_at", "verified_by") or (
                    metadata.get("type") == "rule"
                    and field
                    in ("lifecycle", "level", "priority", "owner", "status", "deprecated_reason")
                ):
                    raise WikiError(
                        "E_FIELD_PROTECTED", "Поле правила меняется только решением ревьюера."
                    )
                if field in ("id", "type", "created", "updated", "verified_at", "verified_by"):
                    raise WikiError("E_PATCH_FIELD", "Это поле меняет только сервис.")
                result[field] = operation["value"]
            elif op in ("add_tag", "remove_tag", "add_source"):
                field, value_key = ("sources", "source") if op == "add_source" else ("tags", "tag")
                values = result.setdefault(field, [])
                value = operation[value_key]
                if op == "remove_tag":
                    if value in values:
                        values.remove(value)
                elif value not in values:
                    values.append(value)
            elif op in ("add_relation", "remove_relation"):
                values = result.setdefault("relations", {}).setdefault(operation["rel"], [])
                value = operation["target"]
                if op == "remove_relation":
                    if value in values:
                        values.remove(value)
                elif value not in values:
                    values.append(value)
                if not values:
                    result["relations"].pop(operation["rel"])
            elif op in ("replace_section", "append_to_section"):
                _, start, end, _ = section_span(body, operation["heading"])
                replacement = "\n" + operation["text"].strip() + "\n\n"
                body = (
                    body[:start]
                    + (body[start:end].rstrip() + "\n" if op == "append_to_section" else "")
                    + replacement
                    + body[end:]
                )
            elif op == "add_section":
                heading, level = operation["heading"], operation.get("level", 2)
                if (
                    level not in (2, 3)
                    or not isinstance(heading, str)
                    or not heading.strip()
                    or "\n" in heading
                    or any(part.heading == heading for part in sections(body))
                ):
                    raise WikiError("E_PATCH_SECTION", "Нужен новый уникальный заголовок H2/H3.")
                after = operation.get("after")
                position = section_span(body, after)[2] if after else len(body)
                body = (
                    body[:position].rstrip()
                    + "\n\n"
                    + "#" * level
                    + " "
                    + heading
                    + "\n\n"
                    + operation["text"].strip()
                    + "\n\n"
                    + body[position:]
                )
            elif op == "replace_text":
                old, new, expected = (
                    operation["old"],
                    operation["new"],
                    operation.get("expect_count", 1),
                )
                if (
                    not old
                    or not isinstance(expected, int)
                    or expected < 1
                    or body.count(old) != expected
                ):
                    raise WikiError(
                        "E_PATCH_COUNT",
                        "Количество совпадений replace_text отличается от expect_count.",
                        "Прочитайте актуальный текст и уточните old/expect_count.",
                    )
                body = body.replace(old, new)
            else:
                raise WikiError("E_PATCH_INVALID", f"Неизвестная операция: {op}.")
    except (KeyError, TypeError, AttributeError, ValueError) as exc:
        raise WikiError("E_PATCH_INVALID", "Некорректные параметры PATCH.") from exc
    return result, body
