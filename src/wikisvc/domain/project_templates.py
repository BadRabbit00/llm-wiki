"""Admin-owned project templates. Templates contain data, never executable hooks."""

import re
from pathlib import PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def validate_template_path(value: str) -> str:
    if (
        not value
        or any(c in value for c in "\\:\x00\r\n")
        or any(part in ("", ".", "..") or part.lower() == ".git" for part in value.split("/"))
    ):
        raise ValueError("Template paths must be relative and remain inside the project")
    return value


class TemplateModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class TemplateFile(TemplateModel):
    path: str
    content: str

    @field_validator("path")
    @classmethod
    def safe_path(cls, value: str) -> str:
        validate_template_path(value)
        if value == ".wiki-project.yaml":
            raise ValueError("The project manifest is managed by wk")
        return value

    @field_validator("content")
    @classmethod
    def bounded_content(cls, value: str) -> str:
        if len(value.encode("utf-8")) > 256 * 1024:
            raise ValueError("Template file exceeds 256 KiB")
        return value


class TemplateComponent(TemplateModel):
    name: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,31}$")
    kind: Literal["svc", "lib"]
    lang: str = ""

    @field_validator("lang")
    @classmethod
    def language_id(cls, value: str) -> str:
        if value and not re.fullmatch(r"LANG-[a-z0-9][a-z0-9-]*", value):
            raise ValueError("Expected a LANG-id")
        return value


class TemplatePolicyBlock(TemplateModel):
    file: str
    profile: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")

    @field_validator("file")
    @classmethod
    def safe_path(cls, value: str) -> str:
        return validate_template_path(value)


class ProjectTemplate(TemplateModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    title: str = Field(min_length=1)
    profile: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    scopes: list[str] = Field(default_factory=list)
    components: list[TemplateComponent] = Field(default_factory=list)
    files: list[TemplateFile] = Field(default_factory=list, max_length=200)
    policy_blocks: list[TemplatePolicyBlock] = Field(default_factory=list)

    @model_validator(mode="after")
    def limits_and_duplicates(self) -> "ProjectTemplate":
        if sum(len(file.content.encode("utf-8")) for file in self.files) > 2 * 1024 * 1024:
            raise ValueError("Template exceeds 2 MiB")
        paths = {file.path for file in self.files}
        if len(paths) != len(self.files):
            raise ValueError("Duplicate template file")
        for path in paths:
            if any(str(parent) in paths for parent in PurePosixPath(path).parents):
                raise ValueError("Template file conflicts with a directory")
        if len({component.name for component in self.components}) != len(self.components):
            raise ValueError("Duplicate template component")
        if len({block.file for block in self.policy_blocks}) != len(self.policy_blocks):
            raise ValueError("Duplicate policy block")
        return self
