from typing import Literal

from wikiagent.planner.claims import StrictModel


# doc: DTO-wikiagent.Intent
class Intent(StrictModel):
    intent: Literal["intake", "question", "edit", "revise", "revert", "cancel", "other"]
    clarification: str | None = None
