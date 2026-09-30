from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from wikisvc import __version__
from wikisvc.api.routers import admin, graph, lint, pages, proposals, raw, schema, search
from wikisvc.config import Settings
from wikisvc.domain.errors import WikiError
from wikisvc.services.runtime import Runtime
from wikisvc.storage.lock import write_lock


class BodyLimit:
    def __init__(self, app: ASGIApp, maximum: int) -> None:
        self.app, self.maximum = app, maximum

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        total = 0
        messages: list[Message] = []
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            total += len(message.get("body", b""))
            if total > self.maximum:
                error = WikiError("E_BODY_TOO_LARGE", "Превышен размер запроса.", status=413)
                await JSONResponse(error.response(), status_code=413)(scope, receive, send)
                return
            messages.append(message)
            if not message.get("more_body", False):
                break

        async def replay() -> Message:
            return messages.pop(0) if messages else await receive()

        await self.app(scope, replay, send)


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or Settings()  # type: ignore[call-arg]

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        runtime = Runtime(config)
        with write_lock(config.state_dir, config.lock_timeout):
            runtime.indexer.reindex()
            runtime.proposals.expire()
        app.state.runtime = runtime
        yield

    app = FastAPI(title="wikisvc", version=__version__, lifespan=lifespan)
    app.add_middleware(BodyLimit, maximum=config.max_upload_mb * 1024 * 1024 + 65536)

    @app.exception_handler(WikiError)
    def wiki_error(request: Request, exc: WikiError) -> JSONResponse:
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            actor = getattr(request.state, "actor", None)
            request.app.state.runtime.state.audit(
                actor.name if actor else "anonymous",
                "request.denied",
                request.url.path,
                ok=False,
                detail=exc.code,
            )
        return JSONResponse(exc.response(), status_code=exc.status)

    @app.exception_handler(Exception)
    def internal_error(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(
            WikiError(
                "E_INTERNAL",
                "Внутренняя ошибка сервиса.",
                "Проверьте состояние сервиса.",
                status=500,
            ).response(),
            status_code=500,
        )

    @app.exception_handler(RequestValidationError)
    def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            WikiError(
                "E_REQUEST_INVALID",
                "Запрос не соответствует API.",
                details=[
                    {"field": ".".join(map(str, e["loc"])), "message": e["msg"]}
                    for e in exc.errors()
                ],
                status=400,
            ).response(),
            status_code=400,
        )

    @app.exception_handler(HTTPException)
    def http_error(request: Request, exc: HTTPException) -> JSONResponse:
        return JSONResponse(
            WikiError("E_HTTP", str(exc.detail), status=exc.status_code).response(),
            status_code=exc.status_code,
        )

    @app.get("/api/v1/health")
    def health(request: Request) -> dict[str, str]:
        with request.app.state.runtime.index.connect() as db:
            row = db.execute("SELECT value FROM meta WHERE key='index_commit'").fetchone()
        return {"status": "ok", "version": __version__, "index_commit": row[0] if row else ""}

    for router in (
        pages.router,
        search.router,
        graph.router,
        schema.router,
        proposals.router,
        raw.router,
        lint.router,
        admin.router,
    ):
        app.include_router(router, prefix="/api/v1")
    return app
