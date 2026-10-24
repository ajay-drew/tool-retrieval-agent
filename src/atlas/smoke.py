from dataclasses import dataclass

from langchain_core.tools import tool
from langsmith import traceable
from langsmith.run_helpers import get_current_run_tree

from atlas.config import Settings
from atlas.llm import build_chat_model
from atlas.tracing import tracing

SMOKE_PROMPT = "What is my USD balance?"


@tool
def get_balance(currency: str) -> dict:
    """Return the account balance for one ISO 4217 currency code."""
    return {"currency": currency, "available": "1250.00"}


@dataclass(frozen=True)
class SmokeResult:
    tool_calls: list[dict]
    trace_url: str | None


@traceable(name="atlas-smoke")
async def _ask(settings: Settings) -> SmokeResult:
    model = build_chat_model(settings).bind_tools([get_balance])
    reply = await model.ainvoke(SMOKE_PROMPT)
    run = get_current_run_tree()
    return SmokeResult(tool_calls=reply.tool_calls, trace_url=run.get_url() if run else None)


async def run_smoke(settings: Settings) -> SmokeResult:
    with tracing(settings):
        return await _ask(settings)
