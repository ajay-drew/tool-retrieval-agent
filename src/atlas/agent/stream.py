import json
from collections.abc import AsyncIterator

from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage
from langsmith import traceable
from langsmith.run_helpers import get_current_run_tree

from atlas.agent.runlog import RunLog
from atlas.agent.turn import summarize
from atlas.tools.registry import coerce_json_strings
from atlas.tracing import langsmith_thread_url, tag_thread

RESULT_PREVIEW_CHARS = 4000


def _tool_result(message: ToolMessage) -> dict:
    try:
        payload = json.loads(message.text)
    except ValueError:
        payload = message.text
    status = payload.get("status") if isinstance(payload, dict) else 200
    body = payload.get("body", payload) if isinstance(payload, dict) else payload
    text = json.dumps(body)
    if len(text) > RESULT_PREVIEW_CHARS:
        body = text[:RESULT_PREVIEW_CHARS] + "…"
    return {
        "type": "tool_result",
        "id": message.tool_call_id,
        "name": message.name,
        "status": status,
        "body": body,
    }


def token_event(message: object, metadata: dict) -> dict | None:
    """A text piece from the model step; tool-call argument chunks are not shown."""
    if metadata.get("langgraph_node") != "model" or not isinstance(message, AIMessageChunk):
        return None
    text = message.text
    return {"type": "token", "text": text} if text else None


async def _injection_warning(agent, config: dict) -> dict:
    state = await agent.aget_state(config)
    flags = state.values.get("injection_flags") or []
    if not flags:
        return {}
    return {
        "warning": "Earlier tool results in this conversation contained text that looked like "
        "instructions to Atlas. Check this change was really asked for: "
        + "; ".join(sorted(set(flags))[:3])
    }


def events_from_update(node: str, update: object, step: int, access: dict[str, str]):
    """Map one LangGraph `updates` chunk to Atlas stream events."""
    if node == "__interrupt__":
        requests = update[0].value["action_requests"]
        yield {
            "type": "approval",
            "requests": [
                {"name": r["name"], "args": r["args"], "description": r.get("description", "")}
                for r in requests
            ],
        }
        return
    if not isinstance(update, dict):
        return
    if "last_retrieval" in update:
        yield {"type": "retrieval", "step": step + 1, **update["last_retrieval"]}
    for message in update.get("messages") or []:
        if isinstance(message, AIMessage):
            for call in message.tool_calls:
                yield {
                    "type": "tool_call",
                    "id": call["id"],
                    "name": call["name"],
                    "args": coerce_json_strings(call["args"]),
                    "access": access.get(call["name"], "read"),
                }
            if message.text:
                yield {"type": "message", "text": message.text}
        elif isinstance(message, ToolMessage):
            yield _tool_result(message)


@traceable(name="atlas-turn")
async def stream_turn(
    agent,
    payload: object,
    thread_id: str,
    user_message: str,
    access: dict[str, str],
    runlog: RunLog | None = None,
) -> AsyncIterator[dict]:
    config = {
        "configurable": {"thread_id": thread_id},
        "metadata": {"thread_id": thread_id},
        "recursion_limit": 60,
    }
    tag_thread(thread_id)
    step = 0
    paused = False
    async for mode, chunk in agent.astream(payload, config, stream_mode=["updates", "messages"]):
        if mode == "messages":
            token = token_event(*chunk)
            if token:
                yield token
            continue
        for node, update in chunk.items():
            for event in events_from_update(node, update, step, access):
                if event["type"] == "retrieval":
                    step = event["step"]
                if event["type"] == "approval":
                    paused = True
                    event = {**event, **await _injection_warning(agent, config)}
                yield event
    run = get_current_run_tree()
    trace_url = None
    if run is not None:
        try:
            trace_url = run.get_url()
        except Exception:
            trace_url = None
    if paused:
        yield {
            "type": "done",
            "status": "awaiting_approval",
            "trace_url": trace_url,
            "thread_url": langsmith_thread_url(trace_url, thread_id),
        }
        return
    state = await agent.aget_state(config)
    writes = {name for name, kind in access.items() if kind == "write"}
    result = summarize(state.values["messages"], writes)
    if runlog:
        runlog.append(
            {
                "thread_id": thread_id,
                "user_message": user_message,
                "status": result.status,
                "tool_calls": [
                    {"name": c.name, "ok": c.ok, "status": c.status} for c in result.tool_calls
                ],
                "langsmith_url": trace_url,
            }
        )
    yield {
        "type": "done",
        "status": result.status,
        "trace_url": trace_url,
        "thread_url": langsmith_thread_url(trace_url, thread_id),
    }
