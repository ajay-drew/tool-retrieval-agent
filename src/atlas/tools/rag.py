import json
from dataclasses import dataclass
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from langchain_core.tools import BaseTool, tool
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import PointStruct

from atlas.retrieval.embedder import Embedder
from atlas.retrieval.index import DENSE, recreate_collection, upsert_batched

RAG_DESCRIPTION = (
    "Search the merchant's own handbook (refund, dispute, invoicing, subscription, shipping and "
    "webhook policies). Use it for questions about how the business does things."
)


@dataclass(frozen=True)
class Chunk:
    source: str
    heading: str
    text: str


def chunk_markdown(path: Path) -> list[Chunk]:
    chunks: list[Chunk] = []
    title, heading, lines = path.stem, "", []
    for line in path.read_text().splitlines():
        if line.startswith("# "):
            title = line[2:].strip()
        elif line.startswith("## "):
            if lines:
                chunks.append(Chunk(path.name, heading or title, " ".join(lines).strip()))
            heading, lines = line[3:].strip(), []
        elif line.strip():
            lines.append(line.strip())
    if lines:
        chunks.append(Chunk(path.name, heading or title, " ".join(lines).strip()))
    return [Chunk(c.source, f"{title} / {c.heading}", c.text) for c in chunks]


def load_chunks(kb_dir: Path) -> list[Chunk]:
    return [c for path in sorted(kb_dir.glob("*.md")) for c in chunk_markdown(path)]


class KnowledgeBase:
    def __init__(self, client: AsyncQdrantClient, embedder: Embedder, collection: str):
        self._client = client
        self._embedder = embedder
        self._collection = collection

    async def rebuild(self, chunks: list[Chunk]) -> int:
        vectors = self._embedder.embed_docs([f"{c.heading}: {c.text}" for c in chunks])
        await recreate_collection(self._client, self._collection, vectors.shape[1], (), False)
        points = [
            PointStruct(
                id=str(uuid5(NAMESPACE_URL, f"{c.source}|{c.heading}")),
                vector={DENSE: v.tolist()},
                payload={"source": c.source, "heading": c.heading, "text": c.text},
            )
            for c, v in zip(chunks, vectors, strict=True)
        ]
        await upsert_batched(self._client, self._collection, points)
        return len(points)

    async def search(self, question: str, k: int = 4) -> list[dict]:
        result = await self._client.query_points(
            self._collection,
            query=self._embedder.embed_query(question).tolist(),
            using=DENSE,
            limit=k,
            with_payload=True,
        )
        return [
            {
                "source": f"{p.payload['source']} › {p.payload['heading']}",
                "text": p.payload["text"],
                "score": round(p.score, 3),
            }
            for p in result.points
        ]


def make_rag_tool(kb: KnowledgeBase) -> BaseTool:
    @tool("rag_search", description=RAG_DESCRIPTION)
    async def rag_search(question: str, k: int = 4) -> str:
        return json.dumps(await kb.search(question, k))

    return rag_search
