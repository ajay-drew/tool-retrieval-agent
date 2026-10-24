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


class ToolRetrievalMiddleware(AgentMiddleware[AtlasState]):
    """Before each model call, keep only the top-k retrieved tools, the always-on tools and
    anything find_tools added."""

    state_schema = AtlasState

    def __init__(self, index: ToolIndex, k: int, always_on: Sequence[str]):
        super().__init__()
        self._index = index
        self._k = k
        self._always_on = list(always_on)
        self._cache: dict[str, list[str]] = {}

    async def _top_k(self, query: str) -> list[str]:
        if query not in self._cache:
            self._cache[query] = [h.name for h in await self._index.search(query, self._k)]
        return self._cache[query]

    async def abefore_model(self, state: AtlasState, runtime: Runtime) -> dict:
        retrieved = await self._top_k(search_text(state["messages"]))
        allowed = _unique([*retrieved, *self._always_on, *state.get("found_tools", [])])
        return {"allowed_tools": allowed}

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        allowed = set(request.state.get("allowed_tools") or self._always_on)
        tools = [t for t in request.tools if getattr(t, "name", None) in allowed]
        return await handler(request.override(tools=tools))
