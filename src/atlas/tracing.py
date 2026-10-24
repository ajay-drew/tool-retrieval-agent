from collections.abc import Iterator
from contextlib import contextmanager

from langsmith import Client, tracing_context

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
