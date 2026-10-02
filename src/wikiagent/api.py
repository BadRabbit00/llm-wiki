import json
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from typing import Annotated, Any, Literal

from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from wikiagent.chat.loop import Chat
from wikiagent.client import WikiClient
from wikiagent.config import AgentConfig, load_config
from wikiagent.jobs.runner import JobRunner
from wikiagent.models import ModelClient
from wikiagent.state import AgentState
from wikisvc.domain.errors import WikiError


class Bind(BaseModel):
    type: Literal["page", "rule", "proposal", "none"] = "none"
    id: str = Field(default="", pattern=r"^[a-z0-9-]*$")


class NewSession(BaseModel):
    bind: Bind = Field(default_factory=Bind)
    profile: str | None = None


class Message(BaseModel):
    text: str = Field(min_length=1, max_length=100000)
    attachments: list[str] = Field(default_factory=list, max_length=10)


class BookJob(BaseModel):
    raw_path: str = Field(pattern=r"^(library|raw)/[a-zA-Z0-9_./-]+$")
    title: str | None = Field(default=None, min_length=3, max_length=120)
    author: str | None = Field(default=None, max_length=200)
    year: str | None = Field(default=None, max_length=10)
    scopes_hint: list[str] = Field(default_factory=list, max_length=20)


def create_app(
    config: AgentConfig | None = None,
    client: WikiClient | None = None,
    models: ModelClient | None = None,
) -> FastAPI:
    config = config or load_config()
    state = AgentState(config.state_dir)
    client = client or WikiClient(config.wikisvc)
    models = models or ModelClient(config, state)
    chat = Chat(client, models, state)
    jobs = JobRunner(state, client, models, chat)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        jobs.recover()
        try:
            yield
        finally:
            jobs.close()

    app = FastAPI(title="wikiagent", lifespan=lifespan)
    app.state.jobs = jobs
    app.state.chat = chat
    app.state.agent_state = state
    app.state.client = client
    app.state.models = models

    def authorize(
        credentials: Annotated[HTTPAuthorizationCredentials, Depends(HTTPBearer())],
    ) -> dict[str, Any]:
        actor = client.whoami(credentials.credentials)
        writer = client.check_writer()
        if actor["role"] not in ("writer", "reviewer", "admin"):
            raise WikiError("E_FORBIDDEN", "Для wikiagent нужна роль writer.", status=403)
        # The fixed agent token can read this corpus. A caller must have its clearance.
        if ["public", "internal", "restricted"].index(actor["clearance"]) < [
            "public",
            "internal",
            "restricted",
        ].index(writer["clearance"]):
            raise WikiError(
                "E_FORBIDDEN",
                "Допуск пользователя ниже допуска рабочего токена агента.",
                status=403,
            )
        return actor

    @app.exception_handler(WikiError)
    def error(request: Any, exc: WikiError) -> JSONResponse:
        return JSONResponse(exc.response(), status_code=exc.status)

    @app.post("/chat/sessions")
    def session(
        payload: NewSession, actor: Annotated[dict[str, Any], Depends(authorize)]
    ) -> dict[str, Any]:
        if payload.profile and payload.profile not in {
            p["id"] for p in client.request("GET", "/profiles")
        }:
            raise WikiError("E_PROFILE_UNKNOWN", "Профиль не найден.", status=404)
        # Resolve binding before storing it, so inaccessible or absent IDs are rejected.
        chat.bound_context({"bind": payload.bind.model_dump()})
        return chat.sessions.create(actor, payload.bind.model_dump(), payload.profile)

    @app.get("/chat/sessions/{session_id}")
    def get_session(
        session_id: str, actor: Annotated[dict[str, Any], Depends(authorize)]
    ) -> dict[str, Any]:
        return chat.sessions.get(session_id, actor)

    @app.post("/chat/sessions/{session_id}/messages")
    def message(
        session_id: str, payload: Message, actor: Annotated[dict[str, Any], Depends(authorize)]
    ) -> StreamingResponse:
        chat.sessions.get(session_id, actor)

        def stream() -> Iterator[str]:
            yield 'event: status\ndata: {"status":"planning"}\n\n'
            try:
                result = chat.message(session_id, actor, payload.text, payload.attachments)
                yield "event: message\ndata: " + json.dumps(result, ensure_ascii=False) + "\n\n"
            except WikiError as exc:
                yield (
                    "event: error\ndata: " + json.dumps(exc.response(), ensure_ascii=False) + "\n\n"
                )

        return StreamingResponse(
            stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"}
        )

    @app.post("/jobs/ingest-book", status_code=202)
    def ingest_book(
        payload: BookJob, actor: Annotated[dict[str, Any], Depends(authorize)]
    ) -> dict[str, Any]:
        vocabulary = client.request("GET", "/scopes")
        if set(payload.scopes_hint) - set(vocabulary) - {"*"}:
            raise WikiError("E_SCOPE_UNKNOWN", "Неизвестная область книги.")
        client.request("POST", "/raw/" + payload.raw_path + "/extract")
        job_id = state.job("ingest_book", actor, payload.model_dump(exclude_none=True))
        jobs.start(job_id)
        return jobs.get(job_id, actor)

    @app.get("/jobs")
    def list_jobs(actor: Annotated[dict[str, Any], Depends(authorize)]) -> dict[str, Any]:
        return {
            "items": [
                jobs.get(row["id"], actor)
                for row in state.rows(
                    "SELECT id FROM jobs WHERE owner=? ORDER BY created_at",
                    (actor.get("person") or actor["name"],),
                )
            ]
        }

    @app.get("/jobs/{job_id}")
    def get_job(
        job_id: str, actor: Annotated[dict[str, Any], Depends(authorize)]
    ) -> dict[str, Any]:
        return jobs.get(job_id, actor)

    @app.post("/jobs/{job_id}/cancel")
    def cancel(job_id: str, actor: Annotated[dict[str, Any], Depends(authorize)]) -> dict[str, Any]:
        jobs.get(job_id, actor)
        state.status(job_id, "cancelled")
        return jobs.get(job_id, actor)

    @app.post("/jobs/{job_id}/resume")
    def resume(job_id: str, actor: Annotated[dict[str, Any], Depends(authorize)]) -> dict[str, Any]:
        job = jobs.get(job_id, actor)
        if job["status"] not in ("failed", "cancelled", "paused", "needs_outline"):
            raise WikiError("E_JOB_STATE", "Эту задачу нельзя возобновить.", status=409)
        jobs.start(job_id)
        return jobs.get(job_id, actor)

    return app
