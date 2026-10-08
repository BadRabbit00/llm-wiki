from fastapi import APIRouter
from pydantic import BaseModel

from wikisvc.api.deps import Reader, Services
from wikisvc.domain.errors import WikiError
from wikisvc.services.auth import can_read
from wikisvc.services.pages import paginate

router = APIRouter(prefix="/people")


class Person(BaseModel):
    person: str
    display_name: str
    updated_at: str


class People(BaseModel):
    items: list[Person]
    next_cursor: str | None


@router.get("")
def people(services: Services, actor: Reader, limit: int = 50, cursor: str | None = None) -> People:
    if not can_read(actor, "internal"):
        raise WikiError("E_FORBIDDEN", "Для справочника людей нужен допуск internal.", status=403)
    rows = services.state.rows("SELECT person,display_name,updated_at FROM people ORDER BY person")
    return People.model_validate(paginate(rows, limit, cursor))
