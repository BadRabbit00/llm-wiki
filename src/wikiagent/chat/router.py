from typing import Literal

from wikiagent.planner.claims import StrictModel


class Intent(StrictModel):
    intent: Literal["intake", "question", "edit", "revert", "cancel", "other"]
    clarification: str | None = None
