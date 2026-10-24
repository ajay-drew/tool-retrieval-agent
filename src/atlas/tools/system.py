import json
from typing import Literal

from langchain_core.tools import BaseTool, tool

from atlas.agent.runlog import RunLog
from atlas.retrieval.index import ToolIndex
from atlas.tools.spec import ToolSpec

SYSTEM_DESCRIPTION = (
    "Look up Atlas itself. scope='tools' searches what Atlas can do (e.g. 'manage invoices'). "
    "scope='runs' returns the most recent requests Atlas handled, with their status and the "
    "tools they called."
)


def make_system_tool(index: ToolIndex, specs: list[ToolSpec], runlog: RunLog) -> BaseTool:
    by_name = {s.name: s for s in specs}

    @tool("system_search", description=SYSTEM_DESCRIPTION)
    async def system_search(query: str, scope: Literal["tools", "runs"] = "tools") -> str:
        if scope == "runs":
            rows = runlog.recent(5)
            keep = ("ts", "user_message", "status", "tool_calls", "error")
            return json.dumps([{k: r.get(k) for k in keep if k in r} for r in rows])
        hits = await index.search(query, 8)
        return json.dumps(
            [
                {
                    "name": h.name,
                    "purpose": by_name[h.name].purpose or by_name[h.name].summary,
                    "access": by_name[h.name].access,
                }
                for h in hits
                if h.name in by_name
            ]
        )

    return system_search
