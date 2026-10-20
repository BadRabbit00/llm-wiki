from typing import Any

from fastapi import APIRouter

from wikisvc.api.deps import Reader, Services, Writer
from wikisvc.domain.errors import WikiError
from wikisvc.domain.project_templates import ProjectTemplate

router = APIRouter(prefix="/schema")


# doc: API-wikisvc.schema.project-template
@router.get("/project-templates/{template_id}")
def project_template(template_id: str, services: Services, actor: Reader) -> ProjectTemplate:
    if template_id in services.registry.invalid_project_templates:
        raise WikiError(
            "E_TEMPLATE_INVALID", services.registry.invalid_project_templates[template_id]
        )
    template = services.registry.project_templates.get(template_id)
    if template is None:
        raise WikiError("E_TEMPLATE_UNKNOWN", "Неизвестный шаблон проекта.", status=404)
    return template


# doc: API-wikisvc.schema.get
@router.get("")
def schema(services: Services, actor: Reader) -> dict[str, Any]:
    return services.registry.model_dump(by_alias=True)


# doc: API-wikisvc.schema.page-type
@router.get("/page-types/{type_name}")
def page_type(type_name: str, services: Services, actor: Reader) -> dict[str, Any]:
    return services.schema.page_template(type_name)


# doc: API-wikisvc.schema.instructions
@router.get("/instructions")
def instructions(services: Services, actor: Reader) -> dict[str, str]:
    return services.schema.instructions()


# doc: API-wikisvc.schema.next-adr-number
@router.post("/next-adr-number")
def next_adr(services: Services, actor: Writer) -> dict[str, str]:
    return services.schema.next_adr(actor)
