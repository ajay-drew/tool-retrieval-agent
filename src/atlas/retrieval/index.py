from dataclasses import dataclass
from typing import Protocol
from uuid import NAMESPACE_URL, uuid5

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    Fusion,
    FusionQuery,
    MatchValue,
    Modifier,
    PayloadSchemaType,
    PointStruct,
    Prefetch,
    SparseVectorParams,
    VectorParams,
)

from atlas.retrieval.embedder import Embedder, SparseEmbedder
from atlas.tools.spec import ToolSpec

UPSERT_BATCH = 256
DENSE = "dense"
SPARSE = "bm25"
PREFETCH = 60


@dataclass(frozen=True)
class Hit:
    name: str
    score: float
    rank: int


class ToolIndex(Protocol):
    async def search(
        self, query: str, k: int, service: str | None = None, heads_only: bool = False
    ) -> list[Hit]: ...


def tool_documents(spec: ToolSpec) -> list[tuple[str, str]]:
    head = f"{spec.name.replace('_', ' ')}: {spec.purpose or spec.summary}. {spec.description}"
    docs = [(head, "head"), *((example, "example") for example in spec.examples)]
    if spec.keywords:
        docs.append((spec.keywords, "keywords"))
    return docs


async def recreate_collection(
    client: AsyncQdrantClient,
    collection: str,
    size: int,
    keyword_fields: tuple[str, ...],
    sparse: bool,
) -> None:
    if await client.collection_exists(collection):
        await client.delete_collection(collection)
    await client.create_collection(
        collection,
        vectors_config={DENSE: VectorParams(size=size, distance=Distance.COSINE)},
        sparse_vectors_config={SPARSE: SparseVectorParams(modifier=Modifier.IDF)}
        if sparse
        else None,
    )
    for field in keyword_fields:
        await client.create_payload_index(collection, field, PayloadSchemaType.KEYWORD)


async def upsert_batched(
    client: AsyncQdrantClient, collection: str, points: list[PointStruct]
) -> None:
    for start in range(0, len(points), UPSERT_BATCH):
        await client.upsert(collection, points=points[start : start + UPSERT_BATCH], wait=True)


def _filter(service: str | None, heads_only: bool) -> Filter | None:
    conditions = []
    if service:
        conditions.append(FieldCondition(key="service", match=MatchValue(value=service)))
    if heads_only:
        conditions.append(FieldCondition(key="kind", match=MatchValue(value="head")))
    return Filter(must=conditions) if conditions else None


class QdrantToolIndex:
    """Several vectors per tool; grouped search scores a tool by its best-matching point.

    With a sparse embedder, dense and BM25 results are merged by reciprocal-rank fusion.
    """

    def __init__(
        self,
        client: AsyncQdrantClient,
        embedder: Embedder,
        collection: str,
        sparse: SparseEmbedder | None = None,
    ):
        self._client = client
        self._embedder = embedder
        self._collection = collection
        self._sparse = sparse

    async def rebuild(self, specs: list[ToolSpec]) -> int:
        rows = [(spec, text, kind) for spec in specs for text, kind in tool_documents(spec)]
        texts = [text for _, text, _ in rows]
        dense = self._embedder.embed_docs(texts)
        sparse = self._sparse.embed_docs(texts) if self._sparse else [None] * len(texts)
        await recreate_collection(
            self._client,
            self._collection,
            dense.shape[1],
            ("tool", "service", "kind"),
            self._sparse is not None,
        )
        points = []
        for (spec, text, kind), vector, sparse_vector in zip(rows, dense, sparse, strict=True):
            vectors: dict = {DENSE: vector.tolist()}
            if sparse_vector is not None:
                vectors[SPARSE] = sparse_vector
            points.append(
                PointStruct(
                    id=str(uuid5(NAMESPACE_URL, f"{spec.name}|{text}")),
                    vector=vectors,
                    payload={
                        "tool": spec.name,
                        "service": spec.service,
                        "kind": kind,
                        "text": text,
                    },
                )
            )
        await upsert_batched(self._client, self._collection, points)
        return len(points)

    async def search(
        self, query: str, k: int, service: str | None = None, heads_only: bool = False
    ) -> list[Hit]:
        query_filter = _filter(service, heads_only)
        dense = self._embedder.embed_query(query).tolist()
        if self._sparse is None:
            result = await self._client.query_points_groups(
                self._collection,
                query=dense,
                using=DENSE,
                group_by="tool",
                limit=k,
                group_size=1,
                query_filter=query_filter,
                with_payload=False,
            )
        else:
            result = await self._client.query_points_groups(
                self._collection,
                prefetch=[
                    Prefetch(query=dense, using=DENSE, limit=PREFETCH, filter=query_filter),
                    Prefetch(
                        query=self._sparse.embed_query(query),
                        using=SPARSE,
                        limit=PREFETCH,
                        filter=query_filter,
                    ),
                ],
                query=FusionQuery(fusion=Fusion.RRF),
                group_by="tool",
                limit=k,
                group_size=1,
                with_payload=False,
            )
        return [
            Hit(name=str(group.id), score=group.hits[0].score, rank=i + 1)
            for i, group in enumerate(result.groups)
        ]
