import re
from typing import Any

NAMED_VALUES = {
    "currency_code": "USD",
    "value": "10.00",
    "country_code": "US",
    "email_address": "jane@example.com",
    "email": "jane@example.com",
    "url": "https://example.com/hooks",
    "intent": "CAPTURE",
    "name": "Sample",
}
PATTERN_CANDIDATES = (
    "2026-10-24T00:00:00Z",
    "2026-10-24",
    "USD",
    "US",
    "1",
    "X1",
    "x",
    "jane@example.com",
    "https://example.com",
)
FORMAT_VALUES = {
    "date": "2026-10-24",
    "date-time": "2026-10-24T00:00:00Z",
    "date_no_time": "2026-10-24",
    "ppaas_date_time_v3": "2026-10-24T00:00:00Z",
    "uri": "https://example.com",
    "email": "jane@example.com",
}


def sample_value(schema: Any, name: str = "", depth: int = 0) -> Any:
    """Smallest value a schema accepts, filling only required fields."""
    if not isinstance(schema, dict) or depth > 8:
        return "x"
    for combinator in ("allOf", "oneOf", "anyOf"):
        if schema.get(combinator):
            merged: dict = {}
            parts = schema[combinator] if combinator == "allOf" else schema[combinator][:1]
            for part in parts:
                if isinstance(part, dict) and not ({"type", "properties", "enum"} & part.keys()):
                    continue
                value = sample_value(part, name, depth + 1)
                if not isinstance(value, dict):
                    return value
                merged.update(value)
            props = {}
            for part in schema[combinator]:
                if isinstance(part, dict):
                    props.update(part.get("properties", {}))
            props.update(schema.get("properties", {}))
            for key in schema.get("required", []):
                merged.setdefault(key, sample_value(props.get(key, {}), key, depth + 1))
            return merged
    if "enum" in schema:
        return schema["enum"][0]
    kind = schema.get("type", "object" if "properties" in schema else "string")
    if kind == "object":
        props = schema.get("properties", {})
        return {
            key: sample_value(props.get(key, {}), key, depth + 1)
            for key in schema.get("required", [])
        }
    if kind == "array":
        count = max(1, schema.get("minItems", 1))
        return [sample_value(schema.get("items", {}), name, depth + 1) for _ in range(count)]
    if kind in ("integer", "number"):
        return max(1, schema.get("minimum", 1))
    if kind == "boolean":
        return True
    if schema.get("pattern"):
        for candidate in (NAMED_VALUES.get(name), *PATTERN_CANDIDATES):
            if candidate and re.search(schema["pattern"], candidate):
                return candidate
    if name in NAMED_VALUES:
        return NAMED_VALUES[name]
    if schema.get("format") in FORMAT_VALUES:
        return FORMAT_VALUES[schema["format"]]
    return "x" * max(1, schema.get("minLength", 1))
