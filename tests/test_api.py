import json

from fastapi.testclient import TestClient

from atlas.api.app import create_app
from atlas.config import Settings


class FakeService:
    def __init__(self):
        self.resumed = None

    async def chat(self, thread_id, message):
        yield {"type": "retrieval", "step": 1, "query": message, "hits": [], "shown": []}
        yield {"type": "message", "text": f"echo {message}"}
        yield {"type": "done", "status": "completed", "trace_url": None}

    async def resume(self, thread_id, decisions):
        self.resumed = decisions
        yield {"type": "done", "status": "completed", "trace_url": None}

    async def search(self, query, k):
        return [{"name": "invoices_create", "score": 0.9, "rank": 1}][:k]

    def meta(self):
        return {"model": "fake", "tools": 115}


class BrokenService(FakeService):
    async def chat(self, thread_id, message):
        yield {"type": "message", "text": "partial"}
        raise RuntimeError("model went away")


def client(service):
    settings = Settings(_env_file=None, langsmith_tracing=False)
    return TestClient(create_app(settings, service))


def lines(response):
    return [json.loads(line) for line in response.text.splitlines() if line]


def test_health_meta_and_search():
    c = client(FakeService())
    assert c.get("/api/health").json() == {"ok": True}
    assert c.get("/api/meta").json()["tools"] == 115
    assert (
        c.get("/api/tools/search", params={"q": "invoice"}).json()[0]["name"] == "invoices_create"
    )


def test_chat_streams_ndjson_starting_with_thread_id():
    response = client(FakeService()).post("/api/chat/stream", json={"message": "hi"})
    events = lines(response)
    assert response.headers["content-type"].startswith("application/x-ndjson")
    assert events[0]["type"] == "started" and events[0]["thread_id"]
    assert [e["type"] for e in events[1:]] == ["retrieval", "message", "done"]


def test_chat_keeps_a_given_thread_id():
    events = lines(
        client(FakeService()).post("/api/chat/stream", json={"message": "hi", "thread_id": "t1"})
    )
    assert events[0]["thread_id"] == "t1"


def test_resume_passes_decisions_and_validates_them():
    service = FakeService()
    c = client(service)
    ok = c.post(
        "/api/chat/t1/resume/stream", json={"decisions": [{"type": "reject", "message": "no"}]}
    )
    assert lines(ok)[-1]["status"] == "completed"
    assert service.resumed == [{"type": "reject", "message": "no"}]
    assert (
        c.post("/api/chat/t1/resume/stream", json={"decisions": [{"type": "maybe"}]}).status_code
        == 422
    )


def test_errors_mid_stream_become_an_error_event():
    events = lines(client(BrokenService()).post("/api/chat/stream", json={"message": "hi"}))
    assert events[-1] == {"type": "error", "detail": "RuntimeError: model went away"}
