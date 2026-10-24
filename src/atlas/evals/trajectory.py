from statistics import mean, quantiles

from atlas.evals.cases import Case
from atlas.evals.scorers import args_match


def _accepted(case: Case, tool: str) -> set[str]:
    return case.accepted(tool)


def exposure_recall(case: Case, exposed: list[list[str]]) -> float | None:
    if not case.indexed_tools:
        return None
    seen = {name for call in exposed for name in call}
    hits = sum(1 for tool in case.indexed_tools if _accepted(case, tool) & seen)
    return hits / len(case.indexed_tools)


def _successful(calls: list[dict]) -> list[dict]:
    return [c for c in calls if c["ok"]]


def _covers_expected(case: Case, calls: list[dict]) -> bool:
    ok_calls = _successful(calls)
    positions = []
    for tool in case.expected_tools:
        accepted = _accepted(case, tool)
        checks = case.arg_checks.get(tool, {})
        matches = [
            i
            for i, c in enumerate(ok_calls)
            if c["name"] in accepted and (not checks or args_match(c["args"], checks))
        ]
        if not matches:
            return False
        positions.append(matches[0])
    return not case.ordered or positions == sorted(positions)


def unexpected_writes(case: Case, calls: list[dict], writes: set[str]) -> list[str]:
    allowed = {name for tool in case.expected_tools for name in _accepted(case, tool)}
    return [
        c["name"] for c in _successful(calls) if c["name"] in writes and c["name"] not in allowed
    ]


def task_completed(case: Case, result: dict, writes: set[str]) -> bool:
    calls = result["tool_calls"]
    if case.category == "clarify":
        attempted_writes = [c for c in calls if c["name"] in writes]
        return not attempted_writes and "?" in result["answer"]
    if result["status"] in ("failed", "limit_hit"):
        return False
    if not _covers_expected(case, calls) or unexpected_writes(case, calls, writes):
        return False
    answer = result["answer"].lower()
    return all(text.lower() in answer for text in case.answer_contains)


def first_call_correct(case: Case, result: dict, always_on: set[str]) -> float | None:
    if not case.indexed_tools:
        return None
    calls = [c for c in result["tool_calls"] if c["name"] not in always_on]
    if not calls:
        return 0.0
    return 1.0 if calls[0]["name"] in _accepted(case, case.indexed_tools[0]) else 0.0


def case_scores(case: Case, result: dict, writes: set[str], always_on: set[str]) -> dict:
    calls = result["tool_calls"]
    return {
        "task_completed": 1.0 if task_completed(case, result, writes) else 0.0,
        "exposure_recall": exposure_recall(case, result["exposed"]),
        "first_call_correct": first_call_correct(case, result, always_on),
        "tool_calls": len(calls),
        "tool_calls_ok": sum(1 for c in calls if c["ok"]),
        "unexpected_writes": len(unexpected_writes(case, calls, writes)),
        "latency_ms": result["latency_ms"],
        "tokens_in": result["tokens_in"],
        "tokens_out": result["tokens_out"],
        "model_calls": result["model_calls"],
        "max_tools_shown": max((len(c) for c in result["exposed"]), default=0),
    }


def _mean(values: list) -> float | None:
    values = [v for v in values if v is not None]
    return round(mean(values), 4) if values else None


def p95(values: list[float]) -> float | None:
    if len(values) < 2:
        return values[0] if values else None
    return round(quantiles(values, n=20, method="inclusive")[18], 1)


def summarize_run(rows: list[dict], price_in: float, price_out: float) -> dict:
    if not rows:
        return {"n": 0}
    calls = sum(r["tool_calls"] for r in rows)
    costs = [(r["tokens_in"] * price_in + r["tokens_out"] * price_out) / 1e6 for r in rows]
    return {
        "n": len(rows),
        "task_completion": _mean([r["task_completed"] for r in rows]),
        "exposure_recall": _mean([r["exposure_recall"] for r in rows]),
        "first_call_correct": _mean([r["first_call_correct"] for r in rows]),
        "tool_execution_success": round(sum(r["tool_calls_ok"] for r in rows) / calls, 4)
        if calls
        else None,
        "unexpected_writes": sum(r["unexpected_writes"] for r in rows),
        "p95_latency_s": p95([r["latency_ms"] / 1000 for r in rows]),
        "mean_latency_s": round(mean(r["latency_ms"] for r in rows) / 1000, 2),
        "mean_tokens_in": round(mean(r["tokens_in"] for r in rows)),
        "cost_per_task_usd": round(mean(costs), 6),
        "mean_model_calls": round(mean(r["model_calls"] for r in rows), 2),
        "max_tools_shown": max(r["max_tools_shown"] for r in rows),
    }
