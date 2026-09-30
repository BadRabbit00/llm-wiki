from typing import Any

from fastapi import APIRouter

from wikisvc.api.deps import Reader, Services, Writer

router = APIRouter(prefix="/schema")


@router.get("")
def schema(services: Services, actor: Reader) -> dict[str, Any]:
    return services.registry.model_dump(by_alias=True)


@router.get("/page-types/{type_name}")
def page_type(type_name: str, services: Services, actor: Reader) -> dict[str, Any]:
    return services.schema.page_template(type_name)


@router.get("/instructions")
def instructions(services: Services, actor: Reader) -> dict[str, str]:
    return services.schema.instructions()


@router.post("/next-adr-number")
def next_adr(services: Services, actor: Writer) -> dict[str, str]:
    return services.schema.next_adr(actor)
