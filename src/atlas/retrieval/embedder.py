import logging
import os
from typing import Protocol

import numpy as np

os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
logging.getLogger("torch.distributed.elastic.multiprocessing.redirects").setLevel(logging.ERROR)

BGE_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


class Embedder(Protocol):
    def embed_docs(self, texts: list[str]) -> np.ndarray: ...

    def embed_query(self, text: str) -> np.ndarray: ...


class BgeEmbedder:
    def __init__(self, model_name: str):
        from sentence_transformers import SentenceTransformer
        from transformers.utils import logging as hf_logging

        hf_logging.set_verbosity_error()
        hf_logging.disable_progress_bar()
        self._model = SentenceTransformer(model_name, device="cpu")

    def _encode(self, texts: list[str]) -> np.ndarray:
        vectors = self._model.encode(
            texts, normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False
        )
        return vectors.astype("float32")

    def embed_docs(self, texts: list[str]) -> np.ndarray:
        return self._encode(texts)

    def embed_query(self, text: str) -> np.ndarray:
        return self._encode([BGE_QUERY_PREFIX + text])[0]


class SparseEmbedder(Protocol):
    def embed_docs(self, texts: list[str]) -> list: ...

    def embed_query(self, text: str): ...


class Bm25Embedder:
    def __init__(self, model_name: str = "Qdrant/bm25"):
        from fastembed import SparseTextEmbedding

        self._model = SparseTextEmbedding(model_name)

    @staticmethod
    def _to_qdrant(embedding):
        from qdrant_client.models import SparseVector

        return SparseVector(indices=embedding.indices.tolist(), values=embedding.values.tolist())

    def embed_docs(self, texts: list[str]) -> list:
        return [self._to_qdrant(e) for e in self._model.embed(texts)]

    def embed_query(self, text: str):
        return self._to_qdrant(next(iter(self._model.query_embed(text))))
