from collections.abc import Awaitable, Callable

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import HumanMessage

REJECTION_MARKERS = ("tool_use_failed", "Tool call validation failed")


def rejected_tool_call(exc: BaseException) -> str | None:
    """The provider's reason when it refused the model's own tool call, else None."""
    body = getattr(exc, "body", None)
    error = body.get("error", body) if isinstance(body, dict) else None
    if isinstance(error, dict) and error.get("code") == "tool_use_failed":
        return str(error.get("message", exc))
    text = str(exc)
    return text if any(marker in text for marker in REJECTION_MARKERS) else None


class ToolCallRepairMiddleware(AgentMiddleware):
    """Some providers (Groq) validate tool arguments server-side and fail the whole request.
    Hand the reason back to the model so it can correct the call, like our own schema checks."""

    def __init__(self, max_repairs: int = 2):
        super().__init__()
        self._max_repairs = max_repairs

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        for attempt in range(self._max_repairs + 1):
            try:
                return await handler(request)
            except Exception as exc:
                reason = rejected_tool_call(exc)
                if reason is None or attempt == self._max_repairs:
                    raise
                note = HumanMessage(
                    "[Atlas] Your last tool call was rejected before it ran: "
                    f"{reason[:600]} Fix the arguments (leave out optional fields you aren't sure "
                    "about) and call the tool again."
                )
                request = request.override(messages=[*request.messages, note])
        raise RuntimeError("unreachable")
