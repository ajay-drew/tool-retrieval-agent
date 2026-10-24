from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from atlas.tools.ingest import ingest_service, safe_name
from atlas.tools.schema import RefResolver, required_paths, trim

SPECS = Path(__file__).resolve().parents[1] / "specs" / "paypal"


@pytest.fixture(scope="module")
def result():
    return ingest_service(SPECS, "paypal")


def test_all_operations_ingested_with_unique_safe_names(result):
    names = [s.name for s in result.specs]
    assert len(names) == 115
    assert len(set(names)) == 115
    assert all("." not in n for n in names)


def test_safe_name_maps_dots_and_prefixes():
    assert safe_name("plans.create", "paypal", False) == "plans_create"
    assert safe_name("invoices.create", "stripe", True) == "stripe__invoices_create"


def test_trimmed_schemas_are_valid_json_schema(result):
    for spec in result.specs:
        Draft202012Validator.check_schema(spec.params_schema)


def test_no_headers_reach_the_model(result):
    for spec in result.specs:
        assert "header" not in spec.params_schema.get("properties", {})


def test_access_tag_follows_http_method(result):
    for spec in result.specs:
        assert spec.access == ("read" if spec.method == "GET" else "write")


def test_trimming_never_drops_a_required_field(result):
    for spec in result.specs:
        full = result.full_schemas[spec.name]
        missing = required_paths(full) - required_paths(spec.params_schema)
        assert not missing, f"{spec.name} lost required fields: {sorted(missing)[:5]}"


def test_trim_drops_read_only_and_examples_but_keeps_required():
    schema = {
        "type": "object",
        "required": ["id"],
        "properties": {
            "id": {"type": "string", "readOnly": True},
            "status": {"type": "string", "readOnly": True},
            "note": {"type": "string", "example": "hi", "x-internal": True},
        },
    }
    out = trim(schema)
    assert set(out["properties"]) == {"id", "note"}
    assert "example" not in out["properties"]["note"]
    assert out["required"] == ["id"]


def test_resolver_follows_required_refs_past_depth_limit():
    doc = {
        "components": {
            "schemas": {
                "A": {
                    "type": "object",
                    "required": ["b"],
                    "properties": {
                        "b": {"$ref": "#/components/schemas/B"},
                        "x": {"type": "string"},
                    },
                },
                "B": {
                    "type": "object",
                    "required": ["c"],
                    "properties": {"c": {"type": "string"}, "y": {"type": "string"}},
                },
            }
        }
    }
    resolved = RefResolver(doc).resolve({"$ref": "#/components/schemas/A"}, max_depth=0)
    assert resolved["properties"]["b"]["properties"] == {"c": {"type": "string"}}
    assert "x" not in resolved["properties"]
