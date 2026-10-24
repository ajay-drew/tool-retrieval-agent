import json
from collections.abc import Awaitable, Callable, Sequence

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import BaseMessage, HumanMessage
from langgraph.runtime import Runtime

from atlas.agent.state import AtlasState
from atlas.retrieval.index import ToolIndex


def search_text(messages: Sequence[BaseMessage], last_n: int = 2) -> str:
    texts = [m.text for m in messages if isinstance(m, HumanMessage)]
    return " ".join(texts[-last_n:])


def _unique(names: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(names))


def estimate_tokens(messages: Sequence[BaseMessage]) -> int:
    chars = 0
    for message in messages:
        chars += len(str(message.content))
        for call in getattr(message, "tool_calls", None) or []:
            chars += len(json.dumps(call.get("args", {}))) + len(call.get("name", ""))
    return chars // 4


def fit_to_budget(candidates: Sequence[str], sizes: dict[str, int], room: int) -> list[str]:
    """Keep candidates in priority order while their schemas fit in `room` tokens."""
    chosen, used = [], 0
    for name in candidates:
        cost = sizes.get(name, 0)
        if used + cost <= room:
            chosen.append(name)
            used += cost
    return chosen


class ToolRetrievalMiddleware(AgentMiddleware[AtlasState]):
    """Before each model call, keep only the top-k retrieved tools, the always-on tools and
    anything find_tools added, within an optional request token budget."""

    state_schema = AtlasState

    def __init__(
        self,
        index: ToolIndex,
        k: int,
        always_on: Sequence[str],
        tool_tokens: dict[str, int] | None = None,
        max_request_tokens: int | None = None,
        fixed_tokens: int = 0,
    ):
        super().__init__()
        self._index = index
        self._k = k
        self._always_on = list(always_on)
        self._tool_tokens = tool_tokens or {}
        self._max_request_tokens = max_request_tokens
        self._fixed_tokens = fixed_tokens
        self._cache: dict[str, list[str]] = {}

    async def _top_k(self, query: str) -> list[str]:
        if query not in self._cache:
            self._cache[query] = [h.name for h in await self._index.search(query, self._k)]
        return self._cache[query]

    async def abefore_model(self, state: AtlasState, runtime: Runtime) -> dict:
        retrieved = await self._top_k(search_text(state["messages"]))
        candidates = _unique([*reversed(state.get("found_tools", [])), *retrieved])
        candidates = [c for c in candidates if c not in self._always_on]
        if self._max_request_tokens:
            used = self._fixed_tokens + estimate_tokens(state["messages"])
            candidates = fit_to_budget(
                candidates, self._tool_tokens, self._max_request_tokens - used
            )
        return {"allowed_tools": _unique([*candidates, *self._always_on])}

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        allowed = set(request.state.get("allowed_tools") or self._always_on)
        tools = [t for t in request.tools if getattr(t, "name", None) in allowed]
        return await handler(request.override(tools=tools))
