from typing import Any

from fastapi import APIRouter

from wikisvc.api.deps import Reader, Services

router = APIRouter()


@router.get("/policies/compile")
def compile_policies(
    services: Services,
    actor: Reader,
    profile: str | None = None,
    scopes: str | None = None,
    budget_tokens: int | None = None,
    enforced: str = "keep_must",
    explain: bool = False,
) -> dict[str, Any]:
    return services.policies.compile(
        actor,
        profile,
        scopes.split(",") if scopes is not None else None,
        budget_tokens,
        enforced,
        explain,
    )


@router.get("/profiles")
def profiles(services: Services, actor: Reader) -> list[dict[str, Any]]:
    return [p.model_dump() for p in sorted(services.registry.profiles.values(), key=lambda p: p.id)]


@router.get("/scopes")
def scopes(services: Services, actor: Reader) -> list[str]:
    return sorted(services.registry.scopes)
