from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from wikisvc.domain.errors import WikiError
from wikisvc.domain.project_templates import ProjectTemplate


class ExtraField(BaseModel):
    type: Literal["str", "int", "list", "dict", "date"] = "str"
    required: bool = False
    enum: list[str] = Field(default_factory=list)
    pattern: str | None = None
    item_enum: list[str] = Field(default_factory=list)
    item_pattern: str | None = None
    min_items: int = 0
    max_items: int | None = None
    max_length: int | None = None
    min: int | None = None
    max: int | None = None
    default: Any = None


# doc: FMT-wikisvc-core.page-type
class PageType(BaseModel):
    type: str
    prefix: str
    path_template: str
    title_ru: str
    required_sections: list[str] = Field(default_factory=list)
    extra_fields: dict[str, ExtraField] = Field(default_factory=dict)
    allowed_relations: list[str] = Field(default_factory=list)
    template: str = ""
    summary_max: int = 200
    sources_required: bool = True


# doc: FMT-wikisvc-core.profiles
class Profile(BaseModel):
    id: str
    title: str
    scopes: list[str]
    budget_tokens: int = Field(default=2000, ge=1)


# doc: FMT-wikisvc-core.relations
class Relation(BaseModel):
    inverse: str
    symmetric: bool = False
    from_types: list[str] = Field(default_factory=list, alias="from")
    to: list[str] = Field(default_factory=list)
    same_type: bool = False
    weight: float = Field(default=1.0, gt=0, le=1)


class ScopeAxis(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    hierarchical: bool = False
    enum: list[str] = Field(default_factory=list)
    source: str | None = Field(default=None, alias="from")


# doc: CLS-wikisvc-core.Registry
class Registry(BaseModel):
    page_types: dict[str, PageType]
    relations: dict[str, Relation]
    tags: list[str]
    scopes: list[str] = Field(default_factory=list)
    scope_axes: dict[str, ScopeAxis] = Field(default_factory=dict)
    domains: dict[str, str] = Field(default_factory=dict)
    profiles: dict[str, Profile] = Field(default_factory=dict)
    synonyms: list[list[str]] = Field(default_factory=list)
    project_templates: dict[str, ProjectTemplate] = Field(default_factory=dict)
    invalid_project_templates: dict[str, str] = Field(default_factory=dict)

    def page_type(self, name: str) -> PageType:
        if name not in self.page_types:
            raise WikiError("E_TYPE_UNKNOWN", f"Неизвестный тип: {name}")
        return self.page_types[name]

    def scope_known(self, scope: str) -> bool:
        """`*`, a listed value, or a value of an axis that is computed (domain, enum, tech pages)."""
        if scope == "*" or scope in self.scopes:
            return True
        axis, _, value = scope.partition(":")
        definition = self.scope_axes.get(axis)
        if axis == "domain" and self.domains:
            return value in self.domains
        if definition is None or not value:
            return False
        return value in definition.enum or definition.source == "tech-pages"

    def scope_matches(self, page_scope: str, query_scope: str) -> bool:
        """A page scope fits a query scope if equal or, on a hierarchical axis, lies under it."""
        if "*" in (page_scope, query_scope) or page_scope == query_scope:
            return True
        axis, _, value = page_scope.partition(":")
        query_axis, _, query_value = query_scope.partition(":")
        definition = self.scope_axes.get(axis)
        hierarchical = (definition is not None and definition.hierarchical) or (
            axis == "domain" and bool(self.domains)
        )
        return hierarchical and axis == query_axis and value.startswith(query_value + "/")

    @classmethod
    def from_documents(
        cls, types: list[dict[str, Any]], relations: dict[str, Any], tags: list[str]
    ) -> "Registry":
        definitions = [PageType.model_validate(value) for value in types]
        return cls(
            page_types={value.type: value for value in definitions}, relations=relations, tags=tags
        )
