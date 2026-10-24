import math
import re
from collections.abc import Callable, Iterable
from statistics import mean

from atlas.evals.cases import Case

KS = (3, 5, 8, 10)
MRR_DEPTH = 10


def hit_positions(case: Case, ranked: list[str], k: int) -> list[int]:
    """0-based first position in the top k of each expected tool or one of its alternatives."""
    positions: list[int] = []
    for tool in case.indexed_tools:
        accepted = case.accepted(tool)
        for i, name in enumerate(ranked[:k]):
            if name in accepted and i not in positions:
                positions.append(i)
                break
    return positions


def recall_at_k(case: Case, ranked: list[str], k: int) -> float:
    return len(hit_positions(case, ranked, k)) / len(case.indexed_tools)


def precision_at_k(case: Case, ranked: list[str], k: int) -> float:
    return len(hit_positions(case, ranked, k)) / k


def reciprocal_rank(case: Case, ranked: list[str], depth: int = MRR_DEPTH) -> float:
    positions = hit_positions(case, ranked, depth)
    return 1.0 / (min(positions) + 1) if positions else 0.0


def ndcg_at_k(case: Case, ranked: list[str], k: int) -> float:
    dcg = sum(1.0 / math.log2(i + 2) for i in hit_positions(case, ranked, k))
    ideal = sum(1.0 / math.log2(i + 2) for i in range(min(len(case.indexed_tools), k)))
    return dcg / ideal if ideal else 0.0


def retrieval_scores(case: Case, ranked: list[str]) -> dict[str, float]:
    scores: dict[str, float] = {"mrr": reciprocal_rank(case, ranked)}
    for k in KS:
        scores[f"recall@{k}"] = recall_at_k(case, ranked, k)
        scores[f"precision@{k}"] = precision_at_k(case, ranked, k)
        scores[f"ndcg@{k}"] = ndcg_at_k(case, ranked, k)
    return scores


def average(rows: Iterable[dict[str, float]]) -> dict[str, float]:
    rows = list(rows)
    if not rows:
        return {}
    return {key: round(mean(r[key] for r in rows if key in r), 4) for key in rows[0]}


def grouped(
    rows: list[tuple[Case, dict[str, float]]], key: Callable[[Case], str]
) -> dict[str, dict[str, float]]:
    buckets: dict[str, list[dict[str, float]]] = {}
    for case, scores in rows:
        buckets.setdefault(key(case), []).append(scores)
    return {name: {"n": len(b), **average(b)} for name, b in sorted(buckets.items())}


_INDEX = re.compile(r"([^\[\]]+)|\[(\d+)\]")


def dig(value: object, dotted: str) -> object:
    for part in dotted.split("."):
        for key, index in _INDEX.findall(part):
            if key:
                if not isinstance(value, dict) or key not in value:
                    return None
                value = value[key]
            else:
                if not isinstance(value, list) or int(index) >= len(value):
                    return None
                value = value[int(index)]
    return value


def _as_number(value: object) -> float | None:
    try:
        return float(str(value).replace(",", "").lstrip("$"))
    except ValueError:
        return None


def value_matches(actual: object, expected: object) -> bool:
    if actual is None:
        return False
    if isinstance(expected, dict):
        if "prefix" in expected:
            return str(actual).startswith(expected["prefix"])
        if "contains" in expected:
            return expected["contains"].lower() in str(actual).lower()
        return False
    a, e = _as_number(actual), _as_number(expected)
    if a is not None and e is not None:
        return math.isclose(a, e)
    return str(actual).strip().lower() == str(expected).strip().lower()


def args_match(args: dict, checks: dict) -> bool:
    return all(value_matches(dig(args, path), expected) for path, expected in checks.items())
