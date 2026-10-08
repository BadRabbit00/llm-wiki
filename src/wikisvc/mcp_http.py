"""Authenticate MCP HTTP requests before the shared request body limit runs."""

from starlette.concurrency import run_in_threadpool
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from wikisvc.domain.errors import WikiError
from wikisvc.mcp_server import _token
from wikisvc.services.runtime import Runtime
from wikisvc.services.sessions import token_name


class MCPHTTPAuth:
    def __init__(self, app: ASGIApp, path: str) -> None:
        self.app = app
        self.path = path.rstrip("/")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"].rstrip("/") != self.path:
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        scheme, _, token = headers.get("authorization", "").partition(" ")
        try:
            runtime: Runtime = scope["app"].state.runtime
            if "authorization" not in headers and runtime.settings.anonymous_access:
                runtime.auth.anonymous()
            else:
                if scheme.lower() != "bearer" or not token:
                    raise WikiError("E_UNAUTHORIZED", "Нужен Bearer-токен.", status=401)
                await run_in_threadpool(runtime.auth.authenticate, token)
                if runtime.settings.session_issuer_token_name and (
                    await run_in_threadpool(token_name, runtime.state, token)
                    == runtime.settings.session_issuer_token_name
                ):
                    raise WikiError(
                        "E_FORBIDDEN", "Выпускающему токену MCP недоступен.", status=403
                    )
        except WikiError as exc:
            await JSONResponse(exc.response(), status_code=exc.status)(scope, receive, send)
            return

        context = _token.set(token)
        try:
            await self.app(scope, receive, send)
        finally:
            _token.reset(context)
