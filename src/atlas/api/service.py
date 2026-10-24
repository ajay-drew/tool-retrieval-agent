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

    def transcript(self, thread_id: str) -> list[dict] | None: ...


async def _recorded(events: AsyncIterator[dict], log: list[dict]) -> AsyncIterator[dict]:
    async for event in events:
        if event["type"] != "token":
            log.append(event)
        yield event


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
        self._threads: dict[str, list[dict]] = {}

    def chat(self, thread_id: str, message: str) -> AsyncIterator[dict]:
        self._messages[thread_id] = message
        turn = {"user": message, "events": []}
        self._threads.setdefault(thread_id, []).append(turn)
        payload = {"messages": [HumanMessage(message)]}
        events = stream_turn(
            self._agent, payload, thread_id, message, self._access, self._deps.runlog
        )
        return _recorded(events, turn["events"])

    def resume(self, thread_id: str, decisions: list[dict]) -> AsyncIterator[dict]:
        payload = Command(resume={"decisions": decisions})
        message = self._messages.get(thread_id, "")
        events = stream_turn(
            self._agent, payload, thread_id, message, self._access, self._deps.runlog
        )
        turns = self._threads.setdefault(thread_id, [{"user": message, "events": []}])
        return _recorded(events, turns[-1]["events"])

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

    def transcript(self, thread_id: str) -> list[dict] | None:
        return self._threads.get(thread_id)

    def meta(self) -> dict:
        return {
            "model": self._settings.atlas_model,
            "tools": len(self._specs),
            "k": self._settings.atlas_k,
            "max_request_tokens": self._settings.atlas_max_request_tokens,
            "tracing": self._settings.tracing_enabled,
        }
