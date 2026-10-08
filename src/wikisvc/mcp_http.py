"""Authenticate MCP HTTP requests before the shared request body limit runs."""

from starlette.concurrency import run_in_threadpool
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from wikisvc.domain.errors import WikiError
from wikisvc.mcp_server import _token
from wikisvc.services.runtime import Runtime


class MCPHTTPAuth:
    def __init__(self, app: ASGIApp, path: str) -> None:
        self.app = app
        self.path = path.rstrip("/")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"].rstrip("/") != self.path:
            await self.app(scope, receive, send)
            return

        scheme, _, token = Headers(scope=scope).get("authorization", "").partition(" ")
        try:
            if scheme.lower() != "bearer" or not token:
                raise WikiError("E_UNAUTHORIZED", "Нужен Bearer-токен.", status=401)
            runtime: Runtime = scope["app"].state.runtime
            await run_in_threadpool(runtime.auth.authenticate, token)
        except WikiError as exc:
            await JSONResponse(exc.response(), status_code=exc.status)(scope, receive, send)
            return

        context = _token.set(token)
        try:
            await self.app(scope, receive, send)
        finally:
            _token.reset(context)
