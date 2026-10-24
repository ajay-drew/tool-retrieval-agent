import json
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from atlas.api.service import AtlasService, ChatService
from atlas.config import Settings, get_settings
from atlas.tracing import tracing

WEB_DIST = Path("web/dist")


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    thread_id: str | None = None


class Decision(BaseModel):
    type: Literal["approve", "reject"]
    message: str | None = None


class ResumeRequest(BaseModel):
    decisions: list[Decision] = Field(min_length=1)


def _ndjson(
    settings: Settings, first: dict, events: Callable[[], AsyncIterator[dict]]
) -> StreamingResponse:
    async def lines() -> AsyncIterator[str]:
        yield json.dumps(first) + "\n"
        with tracing(settings):
            try:
                async for event in events():
                    yield json.dumps(event, default=str) + "\n"
            except Exception as exc:
                yield json.dumps({"type": "error", "detail": f"{type(exc).__name__}: {exc}"}) + "\n"

    return StreamingResponse(lines(), media_type="application/x-ndjson")


def create_app(settings: Settings | None = None, service: ChatService | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title="Atlas", docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.state.service = service

    def chat_service() -> ChatService:
        if app.state.service is None:
            app.state.service = AtlasService(settings)
        return app.state.service

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True}

    @app.get("/api/meta")
    def meta() -> dict:
        return chat_service().meta()

    @app.get("/api/tools/search")
    async def search(q: str, k: int = 10) -> list[dict]:
        return await chat_service().search(q, max(1, min(k, 30)))

    @app.get("/api/chat/{thread_id}")
    def transcript(thread_id: str) -> dict:
        turns = chat_service().transcript(thread_id)
        if turns is None:
            raise HTTPException(404, f"No conversation {thread_id}; it may predate a restart.")
        return {"thread_id": thread_id, "turns": turns}

    @app.post("/api/chat/stream")
    def chat(body: ChatRequest) -> StreamingResponse:
        thread_id = body.thread_id or uuid4().hex
        return _ndjson(
            settings,
            {"type": "started", "thread_id": thread_id},
            lambda: chat_service().chat(thread_id, body.message),
        )

    @app.post("/api/chat/{thread_id}/resume/stream")
    def resume(thread_id: str, body: ResumeRequest) -> StreamingResponse:
        decisions = [d.model_dump(exclude_none=True) for d in body.decisions]
        return _ndjson(
            settings,
            {"type": "started", "thread_id": thread_id},
            lambda: chat_service().resume(thread_id, decisions),
        )

    if WEB_DIST.exists():

        @app.get("/atlas/{thread_id}")
        def thread_page(thread_id: str) -> FileResponse:
            return FileResponse(WEB_DIST / "index.html")

        app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")
    return app
