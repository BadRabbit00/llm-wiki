from typing import Annotated, Any

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import FileResponse

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
def text(path: str, services: Services, actor: Reader) -> dict[str, Any]:
    return services.raw.text(actor, path)


@router.get("/raw/{path:path}")
def download(path: str, services: Services, actor: Reader) -> FileResponse:
    file = services.raw.file(actor, path)
    return FileResponse(
        file,
        filename=file.name,
        media_type="application/octet-stream",
        headers={"X-Content-Trust": "untrusted_external", "X-Content-Type-Options": "nosniff"},
    )
