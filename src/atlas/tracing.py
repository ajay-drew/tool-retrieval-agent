from collections.abc import Iterator
from contextlib import contextmanager

from langsmith import Client, tracing_context
from langsmith.run_helpers import get_current_run_tree

from atlas.config import Settings


def langsmith_client(settings: Settings) -> Client:
    return Client(
        api_key=settings.langsmith_api_key.get_secret_value(),
        api_url=settings.langsmith_endpoint,
    )


@contextmanager
def tracing(settings: Settings) -> Iterator[Client | None]:
    """Scope LangSmith tracing to this block without touching os.environ."""
    if not settings.tracing_enabled:
        with tracing_context(enabled=False):
            yield None
        return
    client = langsmith_client(settings)
    with tracing_context(enabled=True, project_name=settings.langsmith_project, client=client):
        yield client
    client.flush()


def tag_thread(thread_id: str) -> None:
    """Mark the current trace as part of a LangSmith thread (children get it from run config)."""
    run = get_current_run_tree()
    if run is not None:
        run.add_metadata({"thread_id": thread_id})


def langsmith_thread_url(trace_url: str | None, thread_id: str) -> str | None:
    if not trace_url or "/trace/" not in trace_url:
        return None
    return f"{trace_url.split('/trace/')[0]}/t/{thread_id}"
