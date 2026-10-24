import json
from typing import Annotated

from langchain_core.messages import ToolMessage
from langchain_core.tools import BaseTool, InjectedToolCallId, tool
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from atlas.retrieval.index import ToolIndex

FIND_TOOLS_DESCRIPTION = (
    "Search the full tool catalog when none of your current tools fits the next step. "
    "Describe the action in plain words, e.g. 'send an existing invoice' or 'refund a capture'. "
    "Matching tools become callable on your next turn."
)


def make_find_tools(index: ToolIndex, purposes: dict[str, str]) -> BaseTool:
    @tool("find_tools", description=FIND_TOOLS_DESCRIPTION)
    async def find_tools(
        query: str,
        state: Annotated[dict, InjectedState],
        tool_call_id: Annotated[str, InjectedToolCallId],
        k: int = 5,
    ) -> Command:
        hits = await index.search(query, k)
        names = [h.name for h in hits]
        found = list(dict.fromkeys([*state.get("found_tools", []), *names]))
        content = json.dumps([{"name": n, "purpose": purposes.get(n, "")} for n in names])
        return Command(
            update={
                "found_tools": found,
                "messages": [ToolMessage(content, tool_call_id=tool_call_id, name="find_tools")],
            }
        )

    return find_tools
