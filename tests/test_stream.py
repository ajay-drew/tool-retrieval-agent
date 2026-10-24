from types import SimpleNamespace

from langchain_core.messages import AIMessage, ToolMessage

from atlas.agent.stream import events_from_update

ACCESS = {"invoices_create": "write", "invoices_get": "read"}


def collect(node, update, step=0):
    return list(events_from_update(node, update, step, ACCESS))


def test_retrieval_update_becomes_a_numbered_event():
    update = {"last_retrieval": {"query": "q", "hits": [], "shown": ["a"], "dropped": []}}
    (event,) = collect("ToolRetrievalMiddleware.before_model", update, step=2)
    assert event["type"] == "retrieval" and event["step"] == 3 and event["shown"] == ["a"]


def test_model_tool_calls_and_text():
    call = {
        "name": "invoices_create",
        "args": {"body": '{"x": 1}'},
        "id": "c1",
        "type": "tool_call",
    }
    events = collect("model", {"messages": [AIMessage("Creating it.", tool_calls=[call])]})
    assert events[0] == {
        "type": "tool_call",
        "id": "c1",
        "name": "invoices_create",
        "args": {"body": {"x": 1}},
        "access": "write",
    }
    assert events[1] == {"type": "message", "text": "Creating it."}


def test_tool_message_becomes_result_with_status():
    message = ToolMessage(
        '{"status": 404, "body": {"name": "RESOURCE_NOT_FOUND"}}',
        tool_call_id="c1",
        name="invoices_get",
    )
    (event,) = collect("tools", {"messages": [message]})
    assert event["status"] == 404 and event["body"] == {"name": "RESOURCE_NOT_FOUND"}


def test_interrupt_becomes_approval_request():
    interrupt = SimpleNamespace(
        value={
            "action_requests": [{"name": "invoices_create", "args": {"a": 1}, "description": "d"}]
        }
    )
    (event,) = collect("__interrupt__", (interrupt,))
    assert event == {
        "type": "approval",
        "requests": [{"name": "invoices_create", "args": {"a": 1}, "description": "d"}],
    }


def test_non_dict_updates_are_ignored():
    assert collect("model", None) == []


def test_thread_url_comes_from_the_trace_project():
    from atlas.tracing import langsmith_thread_url

    trace = "https://smith.langchain.com/o/org1/projects/p/proj1/trace/abc/run/abc?start_time=x"
    assert (
        langsmith_thread_url(trace, "t9")
        == "https://smith.langchain.com/o/org1/projects/p/proj1/t/t9"
    )
    assert langsmith_thread_url(None, "t9") is None
