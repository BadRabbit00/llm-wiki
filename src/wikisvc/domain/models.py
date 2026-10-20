from datetime import date, datetime
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    field_validator,
    model_serializer,
)

type Role = Literal["reader", "writer", "reviewer", "admin"]
type Sensitivity = Literal["public", "internal", "restricted"]
type EdgeOrigin = Literal["manual", "extracted", "inferred"]

SENSITIVITY_RANK: dict[str, int] = {"public": 0, "internal": 1, "restricted": 2}


# doc: DTO-wikisvc-core.RelationRef
class RelationRef(BaseModel):
    """A relation target with its own weight: `w` replaces the base weight of the relation."""

    model_config = ConfigDict(extra="forbid")

    id: str
    w: float | None = Field(default=None, gt=0, le=1)
    note: str | None = None
    origin: EdgeOrigin = "manual"

    @field_validator("note")
    @classmethod
    def one_line(cls, value: str | None) -> str | None:
        if value is not None and ("\n" in value or "\r" in value):
            raise ValueError("note must be one line")
        return value

    @model_serializer(mode="wrap")
    def without_empty(self, handler: SerializerFunctionWrapHandler) -> dict[str, object]:
        data: dict[str, object] = handler(self)
        return {key: value for key, value in data.items() if value is not None}


# doc: FMT-wikisvc-core.page
class Frontmatter(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    type: str
    title: str = Field(min_length=3, max_length=120)
    summary: str = Field(min_length=20, max_length=200)
    status: Literal["draft", "verified", "outdated"]
    sensitivity: Sensitivity = "internal"
    tags: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    relations: dict[str, list[str | RelationRef]] = Field(default_factory=dict)
    domain: str | None = None
    scopes: list[str] = Field(default_factory=list)
    created: str
    updated: str
    verified_by: str | None = None
    verified_at: str | None = None

    @field_validator("created", "updated", "verified_at", mode="before")
    @classmethod
    def dates(cls, value: Any) -> Any:
        if isinstance(value, (date, datetime)):
            return value.isoformat()
        return value

    @field_validator("created", "updated", "verified_at")
    @classmethod
    def valid_date(cls, value: str | None) -> str | None:
        if value is not None:
            datetime.fromisoformat(value)
        return value

    @field_validator("summary")
    @classmethod
    def single_line(cls, value: str) -> str:
        if "\n" in value or "\r" in value:
            raise ValueError("summary must be one line")
        return value

    @model_serializer(mode="wrap")
    def without_unused_v3(self, handler: SerializerFunctionWrapHandler) -> dict[str, object]:
        """Pages that never used `domain`/`scopes` keep their exact text when re-rendered."""
        data: dict[str, object] = handler(self)
        if data.get("domain") is None:
            data.pop("domain", None)
        if not data.get("scopes"):
            data.pop("scopes", None)
        return data


# doc: CLS-wikisvc-core.Page
class Page(BaseModel):
    frontmatter: Frontmatter
    body_md: str
    path: str = ""
    version: str = ""

    @property
    def id(self) -> str:
        return self.frontmatter.id


# doc: CLS-wikisvc-core.Edge
class Edge(BaseModel):
    model_config = ConfigDict(frozen=True)
    src: str
    dst: str
    rel: str
    kind: Literal["frontmatter", "wikilink", "citation", "inverse"]
    # `weight` is the override from RelationRef.w; None means "base weight of the relation".
    weight: float | None = None
    note: str | None = None
    origin: EdgeOrigin = "manual"


# doc: CLS-wikisvc-core.LintIssue
class LintIssue(BaseModel):
    code: str
    severity: Literal["error", "warning", "info"]
    page: str | None = None
    message: str
    hint: str = "Проверьте страницу и /schema."


# doc: CLS-wikisvc-core.Principal
class Principal(BaseModel):
    name: str
    role: Role
    clearance: Sensitivity
    person: str | None = None
    kind: Literal["agent", "human"] = "agent"

    @property
    def identity(self) -> str:
        return self.person or self.name


# doc: CLS-wikisvc-core.Proposal
class Proposal(BaseModel):
    pid: str
    title: str
    description: str
    author: str
    status: Literal[
        "draft",
        "submitted",
        "changes_requested",
        "accepted",
        "rejected",
        "conflict",
        "abandoned",
        "reverted",
    ]
    base_commit: str
    branch: str
    review_comment: str | None = None
    created_at: str
    updated_at: str
    decided_by: str | None = None
    last_editor: str | None = None
    kind: Literal["manual", "chat", "book", "heal"] = "manual"
    author_identity: str | None = None
    author_kind: Literal["agent", "human"] = "agent"
    accepted_commit: str | None = None
    reverted_commit: str | None = None
