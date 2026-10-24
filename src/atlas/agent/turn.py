import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.types import Command
from langsmith import traceable
from langsmith.run_helpers import get_current_run_tree

from atlas.agent.exposure import record_exposure
from atlas.agent.runlog import RunLog

Approver = Callable[[list[dict]], Awaitable[list[dict]]]


@dataclass
class ToolCallRecord:
    name: str
    args: dict
    status: int | None = None

    @property
    def ok(self) -> bool:
        return self.status is not None and 200 <= self.status < 300


@dataclass
class TurnResult:
    answer: str
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    exposed: list[list[str]] = field(default_factory=list)
    status: str = "completed"
    latency_ms: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    model_calls: int = 0
    error: str | None = None
    trace_url: str | None = None


async def approve_all(requests: list[dict]) -> list[dict]:
    return [{"type": "approve"} for _ in requests]


def _status_of(content: str) -> int | None:
    try:
        payload = json.loads(content)
    except (TypeError, ValueError):
        return None
    return payload.get("status") if isinstance(payload, dict) else 200


def _turn_messages(messages: list) -> list:
    last_human = max(i for i, m in enumerate(messages) if isinstance(m, HumanMessage))
    return messages[last_human + 1 :]


def summarize(messages: list, writes: set[str]) -> TurnResult:
    turn = _turn_messages(messages)
    calls: dict[str, ToolCallRecord] = {}
    result = TurnResult(answer="")
    for message in turn:
        if isinstance(message, AIMessage):
            result.model_calls += 1
            usage = message.usage_metadata or {}
            result.tokens_in += usage.get("input_tokens", 0)
            result.tokens_out += usage.get("output_tokens", 0)
            for call in message.tool_calls:
                calls[call["id"]] = ToolCallRecord(call["name"], call["args"])
            if message.text:
                result.answer = message.text
        elif isinstance(message, ToolMessage) and message.tool_call_id in calls:
            calls[message.tool_call_id].status = _status_of(message.text)
    result.tool_calls = list(calls.values())
    last = turn[-1] if turn else None
    wrote = any(c.name in writes and c.ok for c in result.tool_calls)
    if (
        isinstance(last, AIMessage)
        and "limit" in last.text.lower()
        and "exceed" in last.text.lower()
    ):
        result.status = "limit_hit"
    elif "?" in result.answer and not wrote:
        result.status = "asked_user"
    return result


@traceable(name="atlas-turn")
async def run_turn(
    agent,
    message: str,
    thread_id: str,
    writes: set[str],
    approver: Approver = approve_all,
    runlog: RunLog | None = None,
) -> TurnResult:
    config = {"configurable": {"thread_id": thread_id}, "recursion_limit": 60}
    started = time.perf_counter()
    with record_exposure() as exposed:
        try:
            state = await agent.ainvoke({"messages": [HumanMessage(message)]}, config)
            while state.get("__interrupt__"):
                requests = state["__interrupt__"][0].value["action_requests"]
                decisions = await approver(requests)
                state = await agent.ainvoke(Command(resume={"decisions": decisions}), config)
            result = summarize(state["messages"], writes)
        except Exception as exc:
            result = TurnResult(answer="", status="failed", error=f"{type(exc).__name__}: {exc}")
    result.exposed = list(exposed)
    run = get_current_run_tree()
    result.trace_url = _safe_url(run)
    result.latency_ms = int((time.perf_counter() - started) * 1000)
    if runlog:
        runlog.append(
            {
                "ts": datetime.now(UTC).isoformat(timespec="seconds"),
                "thread_id": thread_id,
                "user_message": message,
                "status": result.status,
                "tool_calls": [
                    {"name": c.name, "ok": c.ok, "status": c.status} for c in result.tool_calls
                ],
                "latency_ms": result.latency_ms,
                "tokens_in": result.tokens_in,
                "tokens_out": result.tokens_out,
                "langsmith_url": result.trace_url,
                **({"error": result.error} if result.error else {}),
            }
        )
    return result


def _safe_url(run) -> str | None:
    if run is None:
        return None
    try:
        return run.get_url()
    except Exception:
        return None


def as_dict(result: TurnResult) -> dict:
    data = asdict(result)
    data["tool_calls"] = [{**asdict(c), "ok": c.ok} for c in result.tool_calls]
    return data
