import asyncio

import pytest
from langchain.agents.middleware import ModelRequest
from langchain_core.messages import AIMessage, HumanMessage

from atlas.agent.repair import ToolCallRepairMiddleware, rejected_tool_call


class Rejected(Exception):
    def __init__(self):
        super().__init__("Error code: 400")
        self.body = {
            "error": {
                "code": "tool_use_failed",
                "message": "parameters for tool invoices_list did not match schema: /query/fields",
            }
        }


def test_detects_provider_tool_rejections_only():
    assert "invoices_list" in rejected_tool_call(Rejected())
    assert rejected_tool_call(RuntimeError("Tool call validation failed: x")) is not None
    assert rejected_tool_call(ValueError("timeout")) is None


def test_feeds_the_reason_back_and_retries():
    seen = []

    async def handler(request):
        seen.append(request.messages)
        if len(seen) == 1:
            raise Rejected()
        return AIMessage("fixed")

    request = ModelRequest(model=None, messages=[HumanMessage("list invoices")], tools=[])
    result = asyncio.run(ToolCallRepairMiddleware().awrap_model_call(request, handler))
    assert result.text == "fixed"
    assert len(seen[1]) == 2 and "rejected before it ran" in seen[1][-1].text


def test_gives_up_after_max_repairs_and_ignores_other_errors():
    async def always_rejected(request):
        raise Rejected()

    async def broken(request):
        raise ValueError("network down")

    request = ModelRequest(model=None, messages=[HumanMessage("x")], tools=[])
    with pytest.raises(Rejected):
        asyncio.run(
            ToolCallRepairMiddleware(max_repairs=1).awrap_model_call(request, always_rejected)
        )
    with pytest.raises(ValueError):
        asyncio.run(ToolCallRepairMiddleware().awrap_model_call(request, broken))
