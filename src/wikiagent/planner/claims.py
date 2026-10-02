from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Category = Literal[
    "code-style",
    "architecture",
    "logging",
    "errors",
    "security",
    "testing",
    "stack",
    "git",
    "build-ci",
    "docs",
    "process",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Claim(StrictModel):
    text: str = Field(min_length=1, max_length=4000)
    kind: Literal["rule", "not_rule"] = "rule"
    id: str = Field(pattern=r"^rule-[a-z0-9]+(?:-[a-z0-9]+)*$")
    title: str = Field(min_length=3, max_length=120)
    thesis: str = Field(min_length=20, max_length=160)
    category: Category
    scopes_guess: list[str] = Field(default_factory=list)
    level_guess: Literal["must", "should"] = "should"
    owner: str | None = None
    aliases: list[str] = Field(min_length=2, max_length=10)
    rationale: str = Field(min_length=1, max_length=4000)
    good_example: str = Field(default="", max_length=4000)
    bad_example: str = Field(default="", max_length=4000)
    impact_terms: list[str] = Field(default_factory=list, max_length=10)
    ambiguous_scope: bool = False


class Claims(StrictModel):
    claims: list[Claim] = Field(max_length=100)
    remove_ids: list[str] = Field(default_factory=list, max_length=10)
