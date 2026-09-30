from typing import Annotated, cast

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from wikisvc.domain.errors import WikiError
from wikisvc.domain.models import Principal, Role
from wikisvc.services.auth import require_role
from wikisvc.services.runtime import Runtime


def runtime(request: Request) -> Runtime:
    return cast(Runtime, request.app.state.runtime)


type Services = Annotated[Runtime, Depends(runtime)]


class Authorize:
    def __init__(self, role: Role = "reader") -> None:
        self.role = role

    def __call__(
        self,
        services: Services,
        request: Request,
        credentials: Annotated[
            HTTPAuthorizationCredentials | None, Depends(HTTPBearer(auto_error=False))
        ],
    ) -> Principal:
        if credentials is None:
            raise WikiError("E_UNAUTHORIZED", "Нужен Bearer-токен.", status=401)
        actor: Principal = getattr(request.state, "actor", None) or services.auth.authenticate(
            credentials.credentials
        )
        request.state.actor = actor
        require_role(actor, self.role)
        return actor


type Reader = Annotated[Principal, Depends(Authorize())]
type Writer = Annotated[Principal, Depends(Authorize("writer"))]
type Reviewer = Annotated[Principal, Depends(Authorize("reviewer"))]
type Admin = Annotated[Principal, Depends(Authorize("admin"))]
