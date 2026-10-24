import asyncio

from langchain.agents.middleware import ModelRequest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool

from atlas.agent.middleware import ToolRetrievalMiddleware, search_text
from atlas.agent.turn import summarize
from atlas.retrieval.index import Hit

ALWAYS_ON = ["rag_search", "system_search", "find_tools"]


class FakeIndex:
    def __init__(self, ranked: list[str]):
        self.ranked = ranked
        self.queries: list[str] = []

    async def search(self, query, k, service=None, heads_only=False):
        self.queries.append(query)
        return [Hit(name, 1.0 - i / 100, i + 1) for i, name in enumerate(self.ranked[:k])]


def make_tools(names):
    tools = []
    for name in names:

        @tool(name, description=f"tool {name}")
        def _t(x: str = "") -> str:
            return x

        tools.append(_t)
    return tools


CATALOG = [f"t{i}" for i in range(20)] + ALWAYS_ON


def run_middleware(index, state, k=3):
    middleware = ToolRetrievalMiddleware(index, k, ALWAYS_ON)
    update = asyncio.run(middleware.abefore_model(state, None))
    seen = {}

    async def handler(request):
        seen["tools"] = [t.name for t in request.tools]
        return AIMessage("ok")

    request = ModelRequest(
        model=None,
        messages=state["messages"],
        tools=make_tools(CATALOG),
        state={**state, **update},
    )
    asyncio.run(middleware.awrap_model_call(request, handler))
    return seen["tools"]


def test_passes_exactly_top_k_plus_always_on():
    index = FakeIndex(["t5", "t2", "t9", "t1"])
    tools = run_middleware(index, {"messages": [HumanMessage("refund a capture")]})
    assert sorted(tools) == sorted(["t5", "t2", "t9", *ALWAYS_ON])


def test_found_tools_are_added_and_count_stays_bounded():
    index = FakeIndex(["t5", "t2", "t9"])
    state = {"messages": [HumanMessage("send it")], "found_tools": ["t14", "t15"]}
    tools = run_middleware(index, state)
    assert {"t14", "t15"} <= set(tools)
    assert len(tools) <= 3 + len(ALWAYS_ON) + 2


def test_search_text_uses_last_two_user_messages():
    messages = [
        HumanMessage("first"),
        AIMessage("a"),
        HumanMessage("second"),
        HumanMessage("third"),
    ]
    assert search_text(messages) == "second third"


def test_summarize_marks_questions_without_writes_as_asked_user():
    messages = [
        HumanMessage("Send an invoice for $50 to"),
        AIMessage("Who should I send it to? I can generate the number for you."),
    ]
    assert summarize(messages, writes={"invoices_create"}).status == "asked_user"


def test_summarize_tracks_tool_status_and_writes():
    call = {"name": "invoices_create", "args": {"body": {}}, "id": "c1", "type": "tool_call"}
    messages = [
        HumanMessage("Draft an invoice"),
        AIMessage("", tool_calls=[call]),
        ToolMessage('{"status": 201, "body": {"id": "INV2-NEW-0001"}}', tool_call_id="c1"),
        AIMessage("Created INV2-NEW-0001. Anything else?"),
    ]
    result = summarize(messages, writes={"invoices_create"})
    assert result.tool_calls[0].ok
    assert result.status == "completed"


def test_budget_keeps_found_tools_first_and_drops_the_rest():
    from atlas.agent.middleware import fit_to_budget

    sizes = {"found": 300, "t1": 500, "t2": 900, "t3": 200}
    assert fit_to_budget(["found", "t1", "t2", "t3"], sizes, 1000) == ["found", "t1", "t3"]
    assert fit_to_budget(["t2"], sizes, 100) == []


def test_request_budget_limits_tools_shown():
    index = FakeIndex(["t5", "t2", "t9"])
    middleware = ToolRetrievalMiddleware(
        index, 3, ALWAYS_ON, {"t5": 400, "t2": 400, "t9": 400}, max_request_tokens=1000
    )
    update = asyncio.run(
        middleware.abefore_model({"messages": [HumanMessage("refund a capture")]}, None)
    )
    assert update["allowed_tools"] == ["t5", "t2", *ALWAYS_ON]
