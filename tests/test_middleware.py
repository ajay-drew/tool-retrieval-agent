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
