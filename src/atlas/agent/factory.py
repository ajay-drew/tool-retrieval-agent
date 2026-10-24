from atlas.agent.build import AgentDeps
from atlas.agent.runlog import RunLog
from atlas.backend.mock import MockPayPal
from atlas.catalog import load_catalog, load_full_schemas
from atlas.config import Settings
from atlas.llm import build_chat_model
from atlas.retrieval.factory import get_embedder, get_tool_index, make_qdrant_client
from atlas.tools.rag import KnowledgeBase


def make_deps(settings: Settings, runlog: RunLog | None = None, fault_rate: float = 0.0):
    client = make_qdrant_client(settings)
    return AgentDeps(
        model=build_chat_model(settings),
        specs=load_catalog(settings),
        backend=MockPayPal(load_full_schemas(settings), fault_rate=fault_rate),
        tool_index=get_tool_index(settings, client),
        knowledge_base=KnowledgeBase(
            client, get_embedder(settings.atlas_embed_model), settings.atlas_kb_collection
        ),
        runlog=runlog or RunLog(settings.atlas_runlog),
    )
