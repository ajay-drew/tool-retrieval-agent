import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from atlas.evals.cases import Case
from atlas.evals.scorers import KS, average, grouped, retrieval_scores
from atlas.retrieval.embedder import Embedder
from atlas.retrieval.index import ToolIndex
from atlas.tools.spec import ToolSpec

RESULTS_DIR = Path("evals/results")
BASELINE_PATH = Path("evals/baselines/r0.json")
LEAKAGE_THRESHOLD = 0.9


@dataclass(frozen=True)
class RetrievalRun:
    summary: dict
    by_split: dict
    by_category: dict
    by_group: dict
    cases: list[dict]


async def run_retrieval(
    index: ToolIndex, cases: list[Case], groups: dict[str, str], heads_only: bool = False
) -> RetrievalRun:
    eligible = [c for c in cases if c.indexed_tools]
    depth = max(KS)
    results = await asyncio.gather(
        *(index.search(c.query, depth, heads_only=heads_only) for c in eligible)
    )
    rows = []
    per_case = []
    for case, hits in zip(eligible, results, strict=True):
        ranked = [h.name for h in hits]
        scores = retrieval_scores(case, ranked)
        rows.append((case, scores))
        per_case.append(
            {
                "id": case.id,
                "split": case.split,
                "query": case.query,
                "expected": case.indexed_tools,
                "top": ranked[:8],
                **scores,
            }
        )
    return RetrievalRun(
        summary={"n": len(rows), **average(s for _, s in rows)},
        by_split=grouped(rows, lambda c: c.split),
        by_category=grouped(rows, lambda c: c.category),
        by_group=grouped(rows, lambda c: groups.get(c.indexed_tools[0], "?")),
        cases=per_case,
    )


def save_run(run: RetrievalRun, config: dict, name: str = "r0") -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = RESULTS_DIR / f"{stamp}-{name}.json"
    path.write_text(
        json.dumps(
            {
                "run": name,
                "config": config,
                "summary": run.summary,
                "by_split": run.by_split,
                "by_category": run.by_category,
                "by_group": run.by_group,
                "cases": run.cases,
            },
            indent=2,
        )
    )
    return path


def leakage(
    cases: list[Case], specs: list[ToolSpec], embedder: Embedder
) -> list[tuple[str, str, float]]:
    examples = [e for s in specs for e in s.examples]
    if not examples:
        return []
    example_vecs = embedder.embed_docs(examples)
    query_vecs = embedder.embed_docs([c.query for c in cases])
    sims = query_vecs @ example_vecs.T
    flagged = []
    for case, row in zip(cases, sims, strict=True):
        best = int(np.argmax(row))
        if row[best] > LEAKAGE_THRESHOLD:
            flagged.append((case.id, examples[best], float(row[best])))
    return flagged
