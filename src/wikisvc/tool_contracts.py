"""Shared HTTP/MCP/model tool declarations; no model client dependency."""

from typing import Any

# name: method, route, path arguments, query arguments, JSON body arguments
CONTRACTS: dict[str, tuple[str, str, tuple[str, ...], tuple[str, ...], tuple[str, ...]]] = {
    "search": (
        "GET",
        "/search",
        (),
        ("q", "type", "tag", "status", "k", "expand", "lifecycle"),
        (),
    ),
    "get_outline": ("GET", "/raw/{path}/outline", ("path",), (), ()),
    "read_source_pages": (
        "GET",
        "/raw/{path}/text",
        ("path",),
        ("pages", "chapter", "max_chars", "offset"),
        (),
    ),
    "get_page": ("GET", "/pages/{id}", ("id",), ("include",), ()),
    "get_rule": ("GET", "/rules/{id}", ("id",), (), ()),
    "get_context": ("GET", "/context/{id}", ("id",), ("depth", "rels", "budget_chars"), ()),
    "get_policies": (
        "GET",
        "/policies/compile",
        (),
        ("profile", "scopes", "budget_tokens", "explain"),
        (),
    ),
    "list_rules": ("GET", "/rules", (), ("q", "lifecycle", "applies_to", "category"), ()),
    "rules_related": ("GET", "/rules/related", (), ("q", "scopes", "limit"), ()),
    "graph_impact": ("GET", "/graph/impact/{id}", ("id",), ("depth", "rels"), ()),
    "create_proposal": ("POST", "/proposals", (), (), ("title", "description", "kind")),
    "put_page": (
        "PUT",
        "/proposals/{pid}/pages/{id}",
        ("pid", "id"),
        (),
        ("frontmatter", "body_md", "base_version"),
    ),
    "patch_page": (
        "PATCH",
        "/proposals/{pid}/pages/{id}",
        ("pid", "id"),
        (),
        ("ops", "base_version"),
    ),
    "validate_proposal": ("GET", "/proposals/{pid}/validate", ("pid",), (), ()),
    "put_notes": ("PUT", "/proposals/{pid}/notes", ("pid",), (), ("notes",)),
}
READ_TOOLS = frozenset(name for name, value in CONTRACTS.items() if value[0] == "GET")
ALLOWLISTS = {
    "chat": frozenset(CONTRACTS),
    "question": READ_TOOLS,
    "book": frozenset(CONTRACTS) - {"put_notes"},
    "heal": frozenset(CONTRACTS) - {"put_page"},
}
REQUIRED = {
    "search": {"q"},
    "rules_related": {"q"},
    "create_proposal": {"title"},
    "put_page": {"frontmatter", "body_md"},
    "patch_page": {"ops"},
    "put_notes": {"notes"},
}


def definitions(mode: str) -> list[dict[str, Any]]:
    result = []
    for name in sorted(ALLOWLISTS[mode]):
        _, _, paths, query, body = CONTRACTS[name]
        properties: dict[str, Any] = {}
        for key in (*paths, *query, *body):
            properties[key] = (
                {"type": "integer"}
                if key
                in (
                    "k",
                    "depth",
                    "limit",
                    "budget_chars",
                    "budget_tokens",
                    "chapter",
                    "max_chars",
                    "offset",
                )
                else {"type": "boolean"}
                if key in ("explain", "expand")
                else {"type": "object", "additionalProperties": True}
                if key in ("frontmatter", "notes")
                else {"type": "array", "items": {"type": "object", "additionalProperties": True}}
                if key == "ops"
                else {"type": "array", "items": {"type": "string"}}
                if key in ("scopes", "lifecycle", "rels")
                else {"type": "string"}
            )
        result.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": "Wiki service "
                    + name
                    + "; only evidence-backed proposals, human review required.",
                    "parameters": {
                        "type": "object",
                        "properties": properties,
                        "required": sorted(set(paths) | REQUIRED.get(name, set())),
                        "additionalProperties": False,
                    },
                },
            }
        )
    return result
