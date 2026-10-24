from statistics import mean, quantiles

from atlas.evals.cases import Case
from atlas.evals.scorers import args_match


def _successful(calls: list[dict]) -> list[dict]:
    return [c for c in calls if c["ok"]]


def _covers_expected(case: Case, calls: list[dict]) -> bool:
    ok_calls = _successful(calls)
    positions = []
    for tool in case.expected_tools:
        accepted = case.accepted(tool)
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
    allowed = {name for tool in case.expected_tools for name in case.accepted(tool)}
    return [
        c["name"] for c in _successful(calls) if c["name"] in writes and c["name"] not in allowed
    ]


def task_completed(case: Case, result: dict, writes: set[str]) -> bool:
    calls = result["tool_calls"]
    if case.category == "clarify":
        attempted_writes = [c for c in calls if c["name"] in writes]
        return not attempted_writes and "?" in result["answer"]
    if result["status"] in ("error", "limit_hit"):
        return False
    if not _covers_expected(case, calls) or unexpected_writes(case, calls, writes):
        return False
    answer = result["answer"].lower()
    return all(text.lower() in answer for text in case.answer_contains)


def case_scores(case: Case, result: dict, writes: set[str]) -> dict:
    calls = result["tool_calls"]
    return {
        "task_completed": 1.0 if task_completed(case, result, writes) else 0.0,
        "tool_calls": len(calls),
        "tool_calls_ok": sum(1 for c in calls if c["ok"]),
        "latency_ms": result["latency_ms"],
        "tokens_in": result["tokens_in"],
        "tokens_out": result["tokens_out"],
    }


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
        "task_completion": round(mean(r["task_completed"] for r in rows), 4),
        "tool_execution_success": round(sum(r["tool_calls_ok"] for r in rows) / calls, 4)
        if calls
        else None,
        "p95_latency_s": p95([r["latency_ms"] / 1000 for r in rows]),
        "cost_per_task_usd": round(mean(costs), 6),
    }
