import math

import pytest

from atlas.evals.cases import Case
from atlas.evals.scorers import (
    args_match,
    dig,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
    value_matches,
)


def case(tools, alternatives=None):
    return Case(
        id="t",
        split="dev",
        category="multi",
        query="q",
        expected_tools=tools,
        alternatives=alternatives or {},
    )


def test_recall_precision_mrr_for_two_tools():
    c = case(["a", "b"])
    ranked = ["x", "a", "y", "b", "z"]
    assert recall_at_k(c, ranked, 3) == 0.5
    assert recall_at_k(c, ranked, 5) == 1.0
    assert precision_at_k(c, ranked, 5) == pytest.approx(2 / 5)
    assert reciprocal_rank(c, ranked) == 0.5


def test_ndcg_perfect_and_partial():
    c = case(["a", "b"])
    assert ndcg_at_k(c, ["a", "b", "x"], 3) == pytest.approx(1.0)
    expected = (1 / math.log2(3) + 1 / math.log2(5)) / (1 + 1 / math.log2(3))
    assert ndcg_at_k(c, ["x", "a", "y", "b"], 5) == pytest.approx(expected)


def test_alternatives_count_as_hits_once():
    c = case(["search"], {"search": ["list"]})
    assert recall_at_k(c, ["list", "search"], 2) == 1.0
    assert precision_at_k(c, ["list", "search"], 2) == 0.5


def test_always_on_tools_are_not_scored_for_retrieval():
    c = case(["rag_search"])
    assert c.indexed_tools == []


def test_dig_paths_with_indexes():
    args = {"body": {"items": [{"unit_amount": {"value": "50.00"}}]}}
    assert dig(args, "body.items[0].unit_amount.value") == "50.00"
    assert dig(args, "body.items[1].unit_amount.value") is None
    assert dig(args, "path.id") is None


def test_value_matching_rules():
    assert value_matches("50.00", "50")
    assert value_matches("$1,200", "1200")
    assert value_matches("2026-09-01T00:00:00Z", {"prefix": "2026-09-01"})
    assert value_matches("Jane@Example.com", "jane@example.com")
    assert not value_matches(None, "x")
    assert args_match({"path": {"id": "PP-1"}}, {"path.id": "PP-1"})
    assert not args_match({"path": {"id": "PP-2"}}, {"path.id": "PP-1"})
