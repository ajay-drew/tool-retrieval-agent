from collections.abc import AsyncIterator
from typing import Protocol

from langchain_core.messages import HumanMessage
from langgraph.types import Command

from atlas.agent.build import AgentOptions, build_atlas
from atlas.agent.factory import make_deps
from atlas.agent.stream import stream_turn
from atlas.config import Settings


class ChatService(Protocol):
    def chat(self, thread_id: str, message: str) -> AsyncIterator[dict]: ...

    def resume(self, thread_id: str, decisions: list[dict]) -> AsyncIterator[dict]: ...

    async def search(self, query: str, k: int) -> list[dict]: ...

    def meta(self) -> dict: ...


class AtlasService:
    """One Atlas agent with approval pauses on; each conversation is a thread_id."""

    def __init__(self, settings: Settings):
        self._settings = settings
        self._deps = make_deps(settings)
        self._agent = build_atlas(
            self._deps,
            AgentOptions(
                k=settings.atlas_k,
                max_request_tokens=settings.atlas_max_request_tokens,
                approve_writes=True,
                today=settings.atlas_today,
            ),
        )
        self._specs = {s.name: s for s in self._deps.specs}
        self._access = {s.name: s.access for s in self._deps.specs}
        self._messages: dict[str, str] = {}

    def chat(self, thread_id: str, message: str) -> AsyncIterator[dict]:
        self._messages[thread_id] = message
        payload = {"messages": [HumanMessage(message)]}
        return stream_turn(
            self._agent, payload, thread_id, message, self._access, self._deps.runlog
        )

    def resume(self, thread_id: str, decisions: list[dict]) -> AsyncIterator[dict]:
        payload = Command(resume={"decisions": decisions})
        message = self._messages.get(thread_id, "")
        return stream_turn(
            self._agent, payload, thread_id, message, self._access, self._deps.runlog
        )

    async def search(self, query: str, k: int) -> list[dict]:
        hits = await self._deps.tool_index.search(query, k)
        return [
            {
                "name": h.name,
                "score": round(h.score, 4),
                "rank": h.rank,
                "purpose": self._specs[h.name].purpose or self._specs[h.name].summary,
                "access": self._specs[h.name].access,
                "group": self._specs[h.name].group,
                "method": self._specs[h.name].method,
                "path": self._specs[h.name].path,
            }
            for h in hits
            if h.name in self._specs
        ]

    def meta(self) -> dict:
        return {
            "model": self._settings.atlas_model,
            "tools": len(self._specs),
            "k": self._settings.atlas_k,
            "max_request_tokens": self._settings.atlas_max_request_tokens,
            "tracing": self._settings.tracing_enabled,
        }
