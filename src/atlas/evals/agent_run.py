import asyncio
import json
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from atlas.agent.build import AgentDeps, AgentOptions, build_atlas
from atlas.agent.runlog import RunLog
from atlas.agent.turn import as_dict, run_turn
from atlas.backend.mock import MockPayPal
from atlas.catalog import load_catalog, load_full_schemas
from atlas.config import Settings
from atlas.evals.cases import Case
from atlas.evals.retrieval import RESULTS_DIR
from atlas.evals.trajectory import case_scores, summarize_run
from atlas.llm import build_chat_model
from atlas.retrieval.factory import get_embedder, get_tool_index, make_qdrant_client
from atlas.tools.rag import KnowledgeBase

EVAL_TODAY = "2026-10-24"
RUNLOG_FIXTURE = Path("evals/fixtures/runlog.jsonl")
NO_OUTPUT = {
    "answer": "",
    "tool_calls": [],
    "status": "error",
    "latency_ms": 0,
    "tokens_in": 0,
    "tokens_out": 0,
    "model_calls": 0,
    "error": "no output",
}


class CaseRunner:
    """Runs one case at a time against a fresh mock, run log and agent."""

    def __init__(self, settings: Settings):
        client = make_qdrant_client(settings)
        self._model = build_chat_model(settings)
        self._full_schemas = load_full_schemas(settings)
        self._index = get_tool_index(settings, client)
        self._kb = KnowledgeBase(
            client, get_embedder(settings.atlas_embed_model), settings.atlas_kb_collection
        )
        self._k = settings.atlas_k
        self.specs = load_catalog(settings)
        self.writes = {s.name for s in self.specs if s.access == "write"}

    async def run(self, case: Case) -> dict:
        workdir = Path(tempfile.mkdtemp(prefix="atlas-eval-"))
        try:
            runlog_path = workdir / "runlog.jsonl"
            if case.category == "system":
                shutil.copy(RUNLOG_FIXTURE, runlog_path)
            deps = AgentDeps(
                model=self._model,
                specs=self.specs,
                backend=MockPayPal(self._full_schemas),
                tool_index=self._index,
                knowledge_base=self._kb,
                runlog=RunLog(runlog_path),
            )
            agent = build_atlas(
                deps, AgentOptions(k=self._k, approve_writes=False, today=EVAL_TODAY)
            )
            result = await run_turn(agent, case.query, f"eval-{case.id}", self.writes)
            return as_dict(result)
        finally:
            shutil.rmtree(workdir, ignore_errors=True)


async def run_cases(runner: CaseRunner, cases: list[Case], concurrency: int) -> dict[str, dict]:
    semaphore = asyncio.Semaphore(concurrency)

    async def one(case: Case) -> tuple[str, dict]:
        async with semaphore:
            return case.id, await runner.run(case)

    return dict(await asyncio.gather(*(one(c) for c in cases)))


def score_outputs(
    cases: list[Case], outputs: dict[str, dict], writes: set[str], settings: Settings
) -> dict:
    rows, per_case, errors = [], [], []
    for case in cases:
        result = outputs.get(case.id) or NO_OUTPUT
        scores = case_scores(case, result, writes)
        if result["status"] == "error":
            errors.append({"id": case.id, "error": (result.get("error") or "")[:300]})
        else:
            rows.append((case, scores))
        per_case.append(
            {
                "id": case.id,
                "split": case.split,
                "category": case.category,
                "query": case.query,
                **scores,
                "status": result["status"],
                "error": result.get("error"),
                "calls": [[c["name"], c["status"]] for c in result["tool_calls"]],
                "answer": result["answer"][:400],
                "trace_url": result.get("trace_url"),
            }
        )
    price = (settings.atlas_price_in_per_m, settings.atlas_price_out_per_m)

    def group(key) -> dict:
        buckets: dict[str, list[dict]] = {}
        for case, scores in rows:
            buckets.setdefault(key(case), []).append(scores)
        return {k: summarize_run(v, *price) for k, v in sorted(buckets.items())}

    return {
        "errors": errors,
        "summary": summarize_run([s for _, s in rows], *price),
        "by_split": group(lambda c: c.split),
        "by_category": group(lambda c: c.category),
        "cases": per_case,
    }


def save_agent_run(report: dict, extra: dict) -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = RESULTS_DIR / f"{stamp}-agent.json"
    path.write_text(json.dumps({"run": "agent", **extra, **report}, indent=2))
    return path
