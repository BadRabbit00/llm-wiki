import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import Headers
from starlette.exceptions import HTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from wikisvc import __version__
from wikisvc.api.routers import admin, graph, lint, pages, proposals, raw, schema, search
from wikisvc.config import Settings
from wikisvc.domain.errors import WikiError
from wikisvc.services.runtime import Runtime
from wikisvc.storage.lock import write_lock

logger = logging.getLogger("wikisvc")


class BodyLimit:
    def __init__(self, app: ASGIApp, config: Settings) -> None:
        self.app, self.config = app, config
        self.last_denied_log = float("-inf")

    async def reject(self, error: WikiError, scope: Scope, receive: Receive, send: Send) -> None:
        if time.monotonic() - self.last_denied_log >= 60:
            logger.warning("Request rejected: %s (at most one message per minute)", error.code)
            self.last_denied_log = time.monotonic()
        await JSONResponse(error.response(), status_code=error.status)(scope, receive, send)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        if scope["path"].startswith("/api/v1/") and scope["path"] != "/api/v1/health":
            scheme, _, token = headers.get("authorization", "").partition(" ")
            try:
                if scheme.lower() != "bearer" or not token:
                    raise WikiError("E_UNAUTHORIZED", "Нужен Bearer-токен.", status=401)
                actor = await run_in_threadpool(scope["app"].state.runtime.auth.authenticate, token)
                scope.setdefault("state", {})["actor"] = actor
            except WikiError as exc:
                await self.reject(exc, scope, receive, send)
                return
        maximum = (
            self.config.max_upload_mb * 1024 * 1024 + 65536
            if scope["method"] == "POST" and scope["path"].rstrip("/") == "/api/v1/raw"
            else 1024 * 1024
        )
        lengths = headers.getlist("content-length")
        if lengths:
            if (
                len(lengths) != 1
                or not lengths[0].isascii()
                or not lengths[0].isdigit()
                or len(lengths[0]) > 20
            ):
                await self.reject(
                    WikiError("E_REQUEST_INVALID", "Некорректный Content-Length.", status=400),
                    scope,
                    receive,
                    send,
                )
                return
            if int(lengths[0]) > maximum:
                await self.reject(
                    WikiError("E_BODY_TOO_LARGE", "Превышен размер запроса.", status=413),
                    scope,
                    receive,
                    send,
                )
                return
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            if len(body) + len(chunk) > maximum:
                error = WikiError("E_BODY_TOO_LARGE", "Превышен размер запроса.", status=413)
                await self.reject(error, scope, receive, send)
                return
            body.extend(chunk)
            if not message.get("more_body", False):
                break

        delivered = False

        async def replay() -> Message:
            nonlocal delivered
            if delivered:
                return await receive()
            delivered = True
            return {"type": "http.request", "body": bytes(body), "more_body": False}

        await self.app(scope, replay, send)


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or Settings()  # type: ignore[call-arg]
    logger.setLevel(config.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        runtime = Runtime(config)
        with write_lock(config.state_dir, config.lock_timeout):
            runtime.indexer.reindex()
            runtime.proposals.expire()
        app.state.runtime = runtime
        yield

    app = FastAPI(title="wikisvc", version=__version__, lifespan=lifespan)
    app.add_middleware(BodyLimit, config=config)

    @app.exception_handler(WikiError)
    def wiki_error(request: Request, exc: WikiError) -> JSONResponse:
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            actor = getattr(request.state, "actor", None)
            if actor:
                request.app.state.runtime.state.audit(
                    actor.name,
                    "request.denied",
                    request.url.path,
                    ok=False,
                    detail=exc.code,
                )
        return JSONResponse(exc.response(), status_code=exc.status)

    @app.exception_handler(Exception)
    def internal_error(request: Request, exc: Exception) -> JSONResponse:
        logger.error("Internal request failure: %s", type(exc).__name__)
        return JSONResponse(
            WikiError(
                "E_INTERNAL",
                "Внутренняя ошибка сервиса.",
                "Проверьте состояние сервиса.",
                status=500,
            ).response(),
            status_code=500,
        )

    @app.exception_handler(RecursionError)
    def recursive_input(request: Request, exc: RecursionError) -> JSONResponse:
        return JSONResponse(
            WikiError(
                "E_REQUEST_INVALID", "Слишком глубокая вложенность данных.", status=400
            ).response(),
            status_code=400,
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
