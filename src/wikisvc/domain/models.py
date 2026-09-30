from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

type Role = Literal["reader", "writer", "reviewer", "admin"]
type Sensitivity = Literal["public", "internal", "restricted"]


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
    relations: dict[str, list[str]] = Field(default_factory=dict)
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


class Page(BaseModel):
    frontmatter: Frontmatter
    body_md: str
    path: str = ""
    version: str = ""

    @property
    def id(self) -> str:
        return self.frontmatter.id


class Edge(BaseModel):
    model_config = ConfigDict(frozen=True)
    src: str
    dst: str
    rel: str
    kind: Literal["frontmatter", "wikilink", "citation", "inverse"]


class LintIssue(BaseModel):
    code: str
    severity: Literal["error", "warning"]
    page: str | None = None
    message: str
    hint: str = "Проверьте страницу и /schema."


class Principal(BaseModel):
    name: str
    role: Role
    clearance: Sensitivity


class Proposal(BaseModel):
    pid: str
    title: str
    description: str
    author: str
    status: Literal[
        "draft", "submitted", "changes_requested", "accepted", "rejected", "conflict", "abandoned"
    ]
    base_commit: str
    branch: str
    review_comment: str | None = None
    created_at: str
    updated_at: str
    decided_by: str | None = None
