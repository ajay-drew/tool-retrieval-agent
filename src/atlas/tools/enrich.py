import asyncio
import hashlib
import json
from collections.abc import Callable
from pathlib import Path

from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel, Field

from atlas.tools.spec import ToolSpec

PROMPT = """You are documenting one API operation for a search index used by a chat agent.

Operation: {name} ({method} {path})
Group: {group}
Summary: {description}
Inputs (JSON Schema, trimmed): {schema}

Return:
- purpose: one plain sentence saying what a business user gets done with this operation.
- examples: {n_examples} different things a merchant might type into a chat assistant that this
  operation would serve:
  - {n_direct} direct requests to do or fetch something with this operation;
  - {n_indirect} questions whose answer needs this operation's data even though they don't
    name it, such as totals, counts, trends, or "did this happen / what's the status" questions.
  Vary the wording and length, use everyday business language rather than API terms, include
  realistic concrete values (amounts, emails, IDs, dates) where it fits, and never mention the
  operation name or HTTP details."""


class Enrichment(BaseModel):
    purpose: str
    examples: list[str] = Field(min_length=3)


def spec_hash(spec: ToolSpec) -> str:
    payload = json.dumps(
        [PROMPT, spec.name, spec.summary, spec.description, spec.params_schema], sort_keys=True
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


class Enricher:
    def __init__(
        self, model: BaseChatModel, cache_path: Path, n_examples: int = 5, concurrency: int = 8
    ):
        self._n_examples = n_examples
        self._model = model.with_structured_output(Enrichment, method="function_calling")
        self._cache_path = cache_path
        self._semaphore = asyncio.Semaphore(concurrency)

    def _hash(self, spec: ToolSpec) -> str:
        return f"{spec_hash(spec)}-{self._n_examples}"

    def _load_cache(self) -> dict:
        return json.loads(self._cache_path.read_text()) if self._cache_path.exists() else {}

    async def _enrich_one(self, spec: ToolSpec) -> Enrichment:
        prompt = PROMPT.format(
            name=spec.name,
            method=spec.method,
            path=spec.path,
            group=spec.group,
            description=spec.description,
            schema=json.dumps(spec.params_schema)[:3000],
            n_examples=self._n_examples,
            n_direct=self._n_examples - self._n_examples * 2 // 5,
            n_indirect=self._n_examples * 2 // 5,
        )
        async with self._semaphore:
            return await self._model.ainvoke(prompt)

    async def run(
        self, specs: list[ToolSpec], on_done: Callable[[str], None] | None = None
    ) -> dict:
        cache = self._load_cache()
        todo = [s for s in specs if cache.get(s.name, {}).get("hash") != self._hash(s)]

        async def work(spec: ToolSpec) -> None:
            result = await self._enrich_one(spec)
            cache[spec.name] = {
                "hash": self._hash(spec),
                "purpose": result.purpose,
                "examples": result.examples[: self._n_examples],
            }
            if on_done:
                on_done(spec.name)

        await asyncio.gather(*(work(s) for s in todo))
        live = {s.name for s in specs}
        cache = {name: cache[name] for name in sorted(cache) if name in live}
        self._cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._cache_path.write_text(json.dumps(cache, indent=2, ensure_ascii=False))
        return cache
