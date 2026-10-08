from fastapi import APIRouter, Request, Response

from wikisvc.api.deps import Reader, Services
from wikisvc.domain.errors import WikiError
from wikisvc.services.sessions import SessionRequest, SessionResponse

router = APIRouter(prefix="/sessions")


@router.post("")
def create(
    payload: SessionRequest,
    request: Request,
    services: Services,
    actor: Reader,
) -> SessionResponse:
    issuer = services.settings.session_issuer_token_name
    if not issuer:
        raise WikiError("E_NOT_FOUND", "Выпуск сессий выключен.", status=404)
    if getattr(request.state, "token_name", None) != issuer or actor.kind != "agent":
        raise WikiError("E_FORBIDDEN", "Токен не может выпускать сессии.", status=403)
    return services.sessions.create(payload, actor)


@router.delete("/current", status_code=204)
def revoke(request: Request, services: Services, actor: Reader) -> Response:
    if not services.settings.session_issuer_token_name:
        raise WikiError("E_NOT_FOUND", "Выпуск сессий выключен.", status=404)
    if actor.kind != "human":
        raise WikiError("E_FORBIDDEN", "Отозвать свою сессию может только человек.", status=403)
    services.auth.revoke(request.state.token_name)
    return Response(status_code=204)
