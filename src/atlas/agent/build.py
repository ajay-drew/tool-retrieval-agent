from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from langchain.agents import create_agent
from langchain.agents.middleware import (
    AgentMiddleware,
    HumanInTheLoopMiddleware,
    ModelCallLimitMiddleware,
    ModelRetryMiddleware,
    ToolCallLimitMiddleware,
    ToolRetryMiddleware,
)
from langchain_core.language_models import BaseChatModel
from langchain_core.utils.function_calling import convert_to_openai_tool
from langgraph.checkpoint.memory import InMemorySaver

from atlas.agent.middleware import ToolRetrievalMiddleware
from atlas.agent.runlog import RunLog
from atlas.backend.base import Backend, BackendTransientError
from atlas.llm import is_retryable_model_error
from atlas.retrieval.index import ToolIndex
from atlas.tools.find import make_find_tools
from atlas.tools.rag import KnowledgeBase, make_rag_tool
from atlas.tools.registry import build_tools
from atlas.tools.schema import approx_tokens
from atlas.tools.spec import ToolSpec
from atlas.tools.system import make_system_tool

PROMPT_PATH = Path(__file__).with_name("prompt.md")
MODEL_CALL_LIMIT = 8
TOOL_CALL_LIMIT = 12


@dataclass(frozen=True)
class AgentOptions:
    k: int = 8
    max_request_tokens: int | None = None
    output_reserve: int = 1024
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


def build_atlas(deps: AgentDeps, options: AgentOptions):
    purposes = {s.name: s.purpose or s.summary for s in deps.specs}
    extra = [
        make_rag_tool(deps.knowledge_base),
        make_system_tool(deps.tool_index, deps.specs, deps.runlog),
        make_find_tools(deps.tool_index, purposes),
    ]
    always_on = [t.name for t in extra]
    tools = [*build_tools(deps.specs, deps.backend), *extra]

    sizes = {t.name: approx_tokens(convert_to_openai_tool(t)) for t in tools}
    prompt = system_prompt(options.today)
    fixed = approx_tokens(prompt) + sum(sizes[n] for n in always_on) + options.output_reserve
    middleware: list[AgentMiddleware] = [
        ToolRetrievalMiddleware(
            deps.tool_index, options.k, always_on, sizes, options.max_request_tokens, fixed
        )
    ]
    if options.approve_writes:
        writes = [s.name for s in deps.specs if s.access == "write"]
        middleware.append(
            HumanInTheLoopMiddleware(
                interrupt_on={n: {"allowed_decisions": ["approve", "reject"]} for n in writes}
            )
        )
    middleware += [
        ModelRetryMiddleware(
            max_retries=5,
            retry_on=is_retryable_model_error,
            initial_delay=15.0,
            max_delay=60.0,
            on_failure="error",
        ),
        ToolRetryMiddleware(
            max_retries=3,
            retry_on=(BackendTransientError,),
            initial_delay=0.2,
            max_delay=2.0,
        ),
        ModelCallLimitMiddleware(run_limit=MODEL_CALL_LIMIT, exit_behavior="end"),
        ToolCallLimitMiddleware(run_limit=TOOL_CALL_LIMIT, exit_behavior="continue"),
    ]
    return create_agent(
        deps.model,
        tools=tools,
        system_prompt=prompt,
        middleware=middleware,
        checkpointer=InMemorySaver(),
        name="atlas",
    )
