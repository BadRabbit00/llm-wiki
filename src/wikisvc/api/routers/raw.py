from typing import Annotated, Any

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from wikisvc.api.deps import Reader, Services, Writer

router = APIRouter()


@router.post("/raw")
def upload(
    services: Services,
    actor: Writer,
    file: Annotated[UploadFile, File()],
    category: Annotated[str, Form()],
    note: Annotated[str, Form()] = "",
) -> dict[str, Any]:
    return services.raw.upload(actor, file.filename or "upload", file.file, category, note)


@router.get("/raw")
def list_files(
    services: Services, actor: Reader, limit: int = 50, cursor: str | None = None
) -> dict[str, Any]:
    return services.raw.list_files(actor, limit=limit, cursor=cursor)


@router.get("/sources/pending")
def pending(
    services: Services, actor: Reader, limit: int = 50, cursor: str | None = None
) -> dict[str, Any]:
    return services.raw.list_files(actor, pending=True, limit=limit, cursor=cursor)


@router.get("/raw/{path:path}/text")
def text(
    path: str,
    services: Services,
    actor: Reader,
    pages: str | None = None,
    chapter: int | None = None,
    max_chars: int = 30000,
    offset: int = 0,
) -> dict[str, Any]:
    return services.raw.text(actor, path, pages, chapter, max_chars, offset)


class Chapter(BaseModel):
    n: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=200)
    page_from: int = Field(ge=1)
    page_to: int = Field(ge=1)


class Outline(BaseModel):
    chapters: list[Chapter] = Field(min_length=1, max_length=5000)


@router.post("/raw/{path:path}/extract", status_code=202)
def extract(path: str, services: Services, actor: Writer) -> dict[str, Any]:
    return services.extractions.start(actor, path)


@router.get("/raw/{path:path}/outline")
def outline(path: str, services: Services, actor: Reader) -> dict[str, Any]:
    return services.extractions.outline(actor, path)


@router.put("/raw/{path:path}/outline")
def replace_outline(
    path: str, payload: Outline, services: Services, actor: Writer
) -> dict[str, Any]:
    return services.extractions.put_outline(actor, path, [c.model_dump() for c in payload.chapters])


@router.get("/raw/{path:path}")
def download(path: str, services: Services, actor: Reader) -> FileResponse:
    file = services.raw.file(actor, path)
    return FileResponse(
        file,
        filename=file.name,
        media_type="application/octet-stream",
        headers={"X-Content-Trust": "untrusted_external", "X-Content-Type-Options": "nosniff"},
    )
