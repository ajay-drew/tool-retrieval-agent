from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse

_seen: ContextVar[list[list[str]] | None] = ContextVar("atlas_exposed_tools", default=None)


@contextmanager
def record_exposure() -> Iterator[list[list[str]]]:
    """Collect the tool names the model was shown on each call inside this block."""
    calls: list[list[str]] = []
    token = _seen.set(calls)
    try:
        yield calls
    finally:
        _seen.reset(token)


class ExposureMiddleware(AgentMiddleware):
    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        calls = _seen.get()
        if calls is not None:
            calls.append([getattr(t, "name", str(t)) for t in request.tools])
        return await handler(request)
