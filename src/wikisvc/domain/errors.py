from typing import Any


class WikiError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        hint: str = "Проверьте запрос и схему через /schema.",
        details: list[dict[str, Any]] | None = None,
        status: int = 422,
    ) -> None:
        super().__init__(message)
        self.code, self.message, self.hint = code, message, hint
        self.details, self.status = details or [], status

    def response(self) -> dict[str, Any]:
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "hint": self.hint,
                "details": self.details,
            }
        }


def not_found() -> WikiError:
    return WikiError("E_NOT_FOUND", "Объект не найден.", status=404)
