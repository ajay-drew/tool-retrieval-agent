from functools import lru_cache

from qdrant_client import AsyncQdrantClient

from atlas.config import Settings
from atlas.retrieval.embedder import BgeEmbedder, Bm25Embedder
from atlas.retrieval.index import QdrantToolIndex


@lru_cache(maxsize=2)
def get_embedder(model_name: str) -> BgeEmbedder:
    return BgeEmbedder(model_name)


@lru_cache(maxsize=1)
def get_bm25() -> Bm25Embedder:
    return Bm25Embedder()


def make_qdrant_client(settings: Settings) -> AsyncQdrantClient:
    api_key = settings.qdrant_api_key.get_secret_value() if settings.qdrant_api_key else None
    return AsyncQdrantClient(url=settings.qdrant_url, api_key=api_key)


def get_tool_index(settings: Settings, client: AsyncQdrantClient | None = None) -> QdrantToolIndex:
    return QdrantToolIndex(
        client or make_qdrant_client(settings),
        get_embedder(settings.atlas_embed_model),
        settings.atlas_tools_collection,
        get_bm25() if settings.atlas_hybrid else None,
    )
