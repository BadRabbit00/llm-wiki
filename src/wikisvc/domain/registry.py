from typing import Any

from pydantic import BaseModel, Field

from wikisvc.domain.errors import WikiError


class ExtraField(BaseModel):
    required: bool = False
    enum: list[str] = Field(default_factory=list)
    pattern: str | None = None


class PageType(BaseModel):
    type: str
    prefix: str
    path_template: str
    title_ru: str
    required_sections: list[str] = Field(default_factory=list)
    extra_fields: dict[str, ExtraField] = Field(default_factory=dict)
    allowed_relations: list[str] = Field(default_factory=list)
    template: str = ""


class Relation(BaseModel):
    inverse: str
    symmetric: bool = False
    from_types: list[str] = Field(default_factory=list, alias="from")
    to: list[str] = Field(default_factory=list)
    same_type: bool = False


class Registry(BaseModel):
    page_types: dict[str, PageType]
    relations: dict[str, Relation]
    tags: list[str]

    def page_type(self, name: str) -> PageType:
        if name not in self.page_types:
            raise WikiError("E_TYPE_UNKNOWN", f"Неизвестный тип: {name}")
        return self.page_types[name]

    @classmethod
    def from_documents(
        cls, types: list[dict[str, Any]], relations: dict[str, Any], tags: list[str]
    ) -> "Registry":
        definitions = [PageType.model_validate(value) for value in types]
        return cls(
            page_types={value.type: value for value in definitions}, relations=relations, tags=tags
        )
