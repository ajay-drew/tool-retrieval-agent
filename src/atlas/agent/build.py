from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from langchain.agents import create_agent
from langchain.agents.middleware import (
    AgentMiddleware,
    HumanInTheLoopMiddleware,
    LLMToolSelectorMiddleware,
    ModelCallLimitMiddleware,
    ToolCallLimitMiddleware,
    ToolRetryMiddleware,
)
from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.memory import InMemorySaver

from atlas.agent.exposure import ExposureMiddleware
from atlas.agent.middleware import ToolRetrievalMiddleware
from atlas.agent.runlog import RunLog
from atlas.backend.base import Backend, BackendTransientError
from atlas.retrieval.index import ToolIndex
from atlas.tools.find import make_find_tools
from atlas.tools.rag import KnowledgeBase, make_rag_tool
from atlas.tools.registry import build_tools
from atlas.tools.spec import ToolSpec
from atlas.tools.system import make_system_tool

PROMPT_PATH = Path(__file__).with_name("prompt.md")
MODEL_CALL_LIMIT = 8
TOOL_CALL_LIMIT = 12

Mode = Literal["retrieval", "all", "llm_selector"]


@dataclass(frozen=True)
class AgentOptions:
    mode: Mode = "retrieval"
    k: int = 8
    use_find_tools: bool = True
    approve_writes: bool = True
    today: str | None = None


@dataclass(frozen=True)
class AgentDeps:
    model: BaseChatModel
    specs: list[ToolSpec]
    backend: Backend
    tool_index: ToolIndex
    knowledge_base: KnowledgeBase
    runlog: RunLog


def system_prompt(today: str | None) -> str:
    day = today or datetime.now(UTC).date().isoformat()
    return PROMPT_PATH.read_text().format(today=day)


def _selection_middleware(deps: AgentDeps, options: AgentOptions, always_on: list[str]):
    if options.mode == "retrieval":
        return [ToolRetrievalMiddleware(deps.tool_index, options.k, always_on)]
    if options.mode == "llm_selector":
        return [
            LLMToolSelectorMiddleware(
                model=deps.model, max_tools=options.k, always_include=always_on
            )
        ]
    return []


def build_atlas(deps: AgentDeps, options: AgentOptions):
    purposes = {s.name: s.purpose or s.summary for s in deps.specs}
    extra = [
        make_rag_tool(deps.knowledge_base),
        make_system_tool(deps.tool_index, deps.specs, deps.runlog),
    ]
    if options.use_find_tools and options.mode == "retrieval":
        extra.append(make_find_tools(deps.tool_index, purposes))
    always_on = [t.name for t in extra]
    tools = [*build_tools(deps.specs, deps.backend), *extra]

    middleware: list[AgentMiddleware] = _selection_middleware(deps, options, always_on)
    if options.approve_writes:
        writes = [s.name for s in deps.specs if s.access == "write"]
        middleware.append(
            HumanInTheLoopMiddleware(
                interrupt_on={n: {"allowed_decisions": ["approve", "reject"]} for n in writes}
            )
        )
    middleware += [
        ToolRetryMiddleware(
            max_retries=3,
            retry_on=(BackendTransientError,),
            initial_delay=0.2,
            max_delay=2.0,
        ),
        ModelCallLimitMiddleware(run_limit=MODEL_CALL_LIMIT, exit_behavior="end"),
        ToolCallLimitMiddleware(run_limit=TOOL_CALL_LIMIT, exit_behavior="continue"),
        ExposureMiddleware(),
    ]
    return create_agent(
        deps.model,
        tools=tools,
        system_prompt=system_prompt(options.today),
        middleware=middleware,
        checkpointer=InMemorySaver(),
        name="atlas",
    )
