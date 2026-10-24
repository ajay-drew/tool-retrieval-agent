import asyncio
import json
from pathlib import Path

import pytest

from atlas.backend.mock import MockPayPal, parse_route
from atlas.tools.ingest import ingest_service
from atlas.tools.registry import build_tools
from atlas.tools.sample import sample_value

SPECS = Path(__file__).resolve().parents[1] / "specs" / "paypal"


@pytest.fixture(scope="module")
def catalog():
    return ingest_service(SPECS, "paypal")


def seeded_args(spec, backend):
    args = sample_value(spec.params_schema)
    route = parse_route(spec.path, {})
    collection = backend._state.get(route.collection, {})
    items = collection.get("items") or []
    for param in (args.get("path") or {}) if isinstance(args, dict) else {}:
        if items:
            args["path"][param] = items[0]["id"]
    return args


def test_every_tool_succeeds_with_a_valid_minimal_input(catalog):
    backend = MockPayPal(catalog.full_schemas)
    tools = {t.name: t for t in build_tools(catalog.specs, backend)}
    failures = []
    for spec in catalog.specs:
        backend.reset()
        args = seeded_args(spec, backend)
        result = json.loads(asyncio.run(tools[spec.name].ainvoke(args)))
        if result["status"] >= 300:
            failures.append((spec.name, result))
    assert not failures, failures[:5]


def test_route_parsing():
    route = parse_route("/v2/invoicing/invoices/{invoice_id}/send", {"invoice_id": "INV-1"})
    assert (route.collection, route.item_id, route.action) == (
        "/v2/invoicing/invoices",
        "INV-1",
        "send",
    )


def test_create_then_send_invoice_chains_ids(catalog):
    backend = MockPayPal(catalog.full_schemas)
    specs = {s.name: s for s in catalog.specs}
    body = {
        "detail": {"currency_code": "USD"},
        "primary_recipients": [{"billing_info": {"email_address": "jane@example.com"}}],
    }
    created = asyncio.run(backend.call(specs["invoices_create"], {"body": body}))
    assert created.status == 201
    sent = asyncio.run(
        backend.call(specs["invoices_send"], {"path": {"invoice_id": created.body["id"]}})
    )
    assert sent.ok and sent.body["status"] == "SENT"


def test_unknown_id_is_404_and_bad_input_is_422(catalog):
    backend = MockPayPal(catalog.full_schemas)
    specs = {s.name: s for s in catalog.specs}
    missing = asyncio.run(backend.call(specs["invoices_get"], {"path": {"invoice_id": "NOPE"}}))
    assert missing.status == 404
    bad = asyncio.run(backend.call(specs["captures_refund"], {"path": {"capture_id": 5}}))
    assert bad.status == 422


def test_transactions_filter_by_date(catalog):
    backend = MockPayPal(catalog.full_schemas)
    spec = next(s for s in catalog.specs if s.name == "search_get")
    query = {"start_date": "2026-09-01T00:00:00Z", "end_date": "2026-09-30T23:59:59Z"}
    result = asyncio.run(backend.call(spec, {"query": query}))
    assert result.body["total_items"] == 5
