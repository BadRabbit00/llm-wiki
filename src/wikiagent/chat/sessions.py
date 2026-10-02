import json
import uuid
from typing import Any

from wikiagent.state import AgentState
from wikisvc.domain.errors import not_found
from wikisvc.storage.state_db import now


class Sessions:
    def __init__(self, state: AgentState) -> None:
        self.state = state

    def create(
        self, actor: dict[str, Any], bind: dict[str, str], profile: str | None
    ) -> dict[str, Any]:
        session_id = uuid.uuid4().hex
        with self.state.connect() as db:
            db.execute(
                "INSERT INTO chat_sessions VALUES (?,?,?,?,?,?,?,?)",
                (
                    session_id,
                    actor.get("person") or actor["name"],
                    actor["clearance"],
                    json.dumps(bind),
                    profile,
                    None,
                    now(),
                    now(),
                ),
            )
        return self.get(session_id, actor)

    def get(self, session_id: str, actor: dict[str, Any]) -> dict[str, Any]:
        rows = self.state.rows("SELECT * FROM chat_sessions WHERE id=?", (session_id,))
        if (
            not rows
            or rows[0]["owner"] != (actor.get("person") or actor["name"])
            or ["public", "internal", "restricted"].index(actor["clearance"])
            < ["public", "internal", "restricted"].index(rows[0]["clearance"])
        ):
            raise not_found()
        result = rows[0]
        result["bind"] = json.loads(result["bind"])
        result["plan"] = json.loads(result["plan"]) if result["plan"] else None
        result["messages"] = self.state.rows(
            "SELECT role,text,plan,created_at FROM chat_messages WHERE session_id=? ORDER BY id",
            (session_id,),
        )
        for message in result["messages"]:
            message["plan"] = json.loads(message["plan"]) if message["plan"] else None
        return result

    def message(
        self, session_id: str, role: str, text: str, plan: dict[str, Any] | None = None
    ) -> None:
        encoded = json.dumps(plan, ensure_ascii=False) if plan is not None else None
        with self.state.connect() as db:
            db.execute(
                "INSERT INTO chat_messages(session_id,role,text,plan,created_at) VALUES (?,?,?,?,?)",
                (session_id, role, text, encoded, now()),
            )
            db.execute(
                "UPDATE chat_sessions SET plan=COALESCE(?,plan),updated_at=? WHERE id=?",
                (encoded, now(), session_id),
            )
