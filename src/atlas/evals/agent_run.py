import asyncio
import hashlib
import json
import random
import shutil
import tempfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from langsmith import Client, aevaluate

from atlas.agent.build import AgentDeps, AgentOptions, Mode, build_atlas
from atlas.agent.runlog import RunLog
from atlas.agent.turn import as_dict, run_turn
from atlas.backend.mock import MockPayPal
from atlas.catalog import load_catalog, load_full_schemas
from atlas.config import Settings
from atlas.evals.cases import ALWAYS_ON, Case
from atlas.evals.retrieval import RESULTS_DIR
from atlas.evals.trajectory import case_scores, summarize_run, task_completed
from atlas.llm import build_chat_model
from atlas.retrieval.factory import get_embedder, get_tool_index, make_qdrant_client
from atlas.retrieval.index import Hit, ToolIndex
from atlas.tools.rag import KnowledgeBase
from atlas.tools.spec import ToolSpec

EVAL_TODAY = "2026-10-24"
RUNLOG_FIXTURE = Path("evals/fixtures/runlog.jsonl")
DATASET_PREFIX = "atlas-paypal"


@dataclass(frozen=True)
class RunConfig:
    mode: Mode = "retrieval"
    k: int = 8
    use_find_tools: bool = True
    heads_only: bool = False
    untrimmed: bool = False
    sample: int | None = None


RUNS: dict[str, RunConfig] = {
    "r1-all": RunConfig(mode="all"),
    "r1-untrimmed": RunConfig(mode="all", untrimmed=True, sample=30),
    "r2": RunConfig(),
    "r3-k3": RunConfig(k=3),
    "r3-k5": RunConfig(k=5),
    "r3-k12": RunConfig(k=12),
    "r3-heads": RunConfig(heads_only=True),
    "r3-nofind": RunConfig(use_find_tools=False),
    "r3-llmselect": RunConfig(mode="llm_selector"),
}


class HeadsOnlyIndex:
    def __init__(self, inner: ToolIndex):
        self._inner = inner

    async def search(
        self, query: str, k: int, service: str | None = None, heads_only: bool = False
    ) -> list[Hit]:
        return await self._inner.search(query, k, service, heads_only=True)


class CaseRunner:
    """Runs one case at a time against a fresh mock, run log and agent."""

    def __init__(self, settings: Settings, config: RunConfig):
        self._config = config
        client = make_qdrant_client(settings)
        embedder = get_embedder(settings.atlas_embed_model)
        self._model = build_chat_model(settings)
        self._full_schemas = load_full_schemas(settings)
        self.specs = self._specs(load_catalog(settings))
        index = get_tool_index(settings, client)
        self._index = HeadsOnlyIndex(index) if config.heads_only else index
        self._kb = KnowledgeBase(client, embedder, settings.atlas_kb_collection)
        self.writes = {s.name for s in self.specs if s.access == "write"}

    def _specs(self, specs: list[ToolSpec]) -> list[ToolSpec]:
        if not self._config.untrimmed:
            return specs
        return [s.model_copy(update={"params_schema": self._full_schemas[s.name]}) for s in specs]

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
            options = AgentOptions(
                mode=self._config.mode,
                k=self._config.k,
                use_find_tools=self._config.use_find_tools,
                approve_writes=False,
                today=EVAL_TODAY,
            )
            agent = build_atlas(deps, options)
            result = await run_turn(agent, case.query, f"eval-{case.id}", self.writes)
            return as_dict(result)
        finally:
            shutil.rmtree(workdir, ignore_errors=True)


def select_cases(cases: list[Case], config: RunConfig) -> list[Case]:
    if config.sample is None or config.sample >= len(cases):
        return cases
    return sorted(random.Random(42).sample(cases, config.sample), key=lambda c: c.id)


def dataset_name(cases: list[Case]) -> str:
    digest = hashlib.sha256("".join(c.model_dump_json() for c in cases).encode()).hexdigest()[:8]
    return f"{DATASET_PREFIX}-{digest}"


def ensure_dataset(client: Client, cases: list[Case]) -> str:
    name = dataset_name(cases)
    if client.has_dataset(dataset_name=name):
        return name
    dataset = client.create_dataset(
        name, description="Atlas eval cases (tools/evals/cases.jsonl), one example per case."
    )
    client.create_examples(
        dataset_id=dataset.id,
        examples=[
            {
                "inputs": {"case_id": c.id, "query": c.query},
                "outputs": {"case": c.model_dump()},
                "metadata": {"split": c.split, "category": c.category},
                "split": c.split,
            }
            for c in cases
        ],
    )
    return name


def _evaluators(writes: set[str]):
    always_on = set(ALWAYS_ON)

    def completed(outputs: dict, reference_outputs: dict) -> dict:
        case = Case.model_validate(reference_outputs["case"])
        return {"key": "task_completed", "score": int(task_completed(case, outputs, writes))}

    def exposure(outputs: dict, reference_outputs: dict) -> dict:
        case = Case.model_validate(reference_outputs["case"])
        score = case_scores(case, outputs, writes, always_on)["exposure_recall"]
        return {"key": "exposure_recall", "score": score}

    def execution(outputs: dict) -> dict:
        calls = outputs["tool_calls"]
        score = sum(c["ok"] for c in calls) / len(calls) if calls else None
        return {"key": "tool_execution_success", "score": score}

    return [completed, exposure, execution]


async def run_local(runner: CaseRunner, cases: list[Case], concurrency: int) -> dict[str, dict]:
    semaphore = asyncio.Semaphore(concurrency)

    async def one(case: Case) -> tuple[str, dict]:
        async with semaphore:
            return case.id, await runner.run(case)

    return dict(await asyncio.gather(*(one(c) for c in cases)))


async def run_langsmith(
    runner: CaseRunner,
    cases: list[Case],
    name: str,
    config: RunConfig,
    concurrency: int,
    client: Client,
) -> tuple[dict[str, dict], str | None]:
    by_id = {c.id: c for c in cases}
    dataset = ensure_dataset(client, cases)

    async def target(inputs: dict) -> dict:
        return await runner.run(by_id[inputs["case_id"]])

    examples = [
        e for e in client.list_examples(dataset_name=dataset) if e.inputs["case_id"] in by_id
    ]
    results = await aevaluate(
        target,
        data=examples,
        evaluators=_evaluators(runner.writes),
        experiment_prefix=f"atlas-{name}",
        metadata={"run": name, **asdict(config)},
        max_concurrency=concurrency,
        client=client,
    )
    outputs: dict[str, dict] = {}
    async for row in results:
        outputs[row["example"].inputs["case_id"]] = row["run"].outputs or {}
    return outputs, results.experiment_name


def score_outputs(
    cases: list[Case], outputs: dict[str, dict], writes: set[str], settings: Settings
) -> dict:
    always_on = set(ALWAYS_ON)
    rows, per_case = [], []
    for case in cases:
        result = outputs.get(case.id) or {
            "answer": "",
            "tool_calls": [],
            "exposed": [],
            "status": "failed",
            "latency_ms": 0,
            "tokens_in": 0,
            "tokens_out": 0,
            "model_calls": 0,
            "error": "no output",
        }
        scores = case_scores(case, result, writes, always_on)
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
        "summary": summarize_run([s for _, s in rows], *price),
        "by_split": group(lambda c: c.split),
        "by_category": group(lambda c: c.category),
        "cases": per_case,
    }


def save_agent_run(name: str, config: RunConfig, report: dict, extra: dict) -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = RESULTS_DIR / f"{stamp}-{name}.json"
    path.write_text(
        json.dumps({"run": name, "config": asdict(config), **extra, **report}, indent=2)
    )
    return path
