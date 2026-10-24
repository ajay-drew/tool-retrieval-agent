from atlas.evals.cases import Case
from atlas.evals.trajectory import p95, task_completed, unexpected_writes

WRITES = {"invoices_create", "invoices_send", "invoices_cancel"}


def make_case(**kw):
    base = {"id": "c", "split": "test", "category": "multi", "query": "q"}
    return Case.model_validate({**base, **kw})


def call(name, ok=True, args=None):
    return {"name": name, "args": args or {}, "status": 201 if ok else 422, "ok": ok}


def result(calls, answer="Done.", status="completed"):
    return {"tool_calls": calls, "answer": answer, "status": status}


def test_ordered_multi_step_with_arg_check():
    case = make_case(
        expected_tools=["invoices_create", "invoices_send"],
        ordered=True,
        arg_checks={"invoices_create": {"body.amount": "50"}},
    )
    good = [call("invoices_create", args={"body": {"amount": "50.00"}}), call("invoices_send")]
    assert task_completed(case, result(good), WRITES)
    assert not task_completed(case, result(list(reversed(good))), WRITES)
    wrong_amount = [call("invoices_create", args={"body": {"amount": "5"}}), call("invoices_send")]
    assert not task_completed(case, result(wrong_amount), WRITES)


def test_failed_call_then_retry_counts():
    case = make_case(expected_tools=["invoices_create"])
    calls = [call("invoices_create", ok=False), call("invoices_create")]
    assert task_completed(case, result(calls), WRITES)


def test_unexpected_write_fails_the_task():
    case = make_case(expected_tools=["invoices_create"])
    calls = [call("invoices_create"), call("invoices_cancel")]
    assert unexpected_writes(case, calls, WRITES) == ["invoices_cancel"]
    assert not task_completed(case, result(calls), WRITES)


def test_clarify_case_needs_a_question_and_no_write_attempt():
    case = make_case(category="clarify", expect_question=True)
    assert task_completed(case, result([], answer="Who should I bill?"), WRITES)
    assert not task_completed(case, result([], answer="Okay."), WRITES)
    tried = [call("invoices_create", ok=False)]
    assert not task_completed(case, result(tried, answer="Who?"), WRITES)


def test_rag_answer_must_contain_facts():
    case = make_case(category="rag", expected_tools=["rag_search"], answer_contains=["14 days"])
    calls = [{"name": "rag_search", "args": {}, "status": 200, "ok": True}]
    assert task_completed(case, result(calls, answer="Digital: 14 days."), WRITES)
    assert not task_completed(case, result(calls, answer="Two weeks."), WRITES)


def test_limit_hit_is_never_complete():
    case = make_case(expected_tools=["invoices_create"])
    assert not task_completed(case, result([call("invoices_create")], status="limit_hit"), WRITES)


def test_p95():
    assert p95([1.0]) == 1.0
    assert p95([float(i) for i in range(1, 101)]) == 95.0
