import json
from typing import Any

DROP_KEYS = {"example", "examples", "discriminator", "externalDocs", "xml"}
NESTED_LISTS = ("allOf", "anyOf", "oneOf")


def approx_tokens(obj: Any) -> int:
    return len(json.dumps(obj, separators=(",", ":"))) // 4


class RefResolver:
    def __init__(self, document: dict):
        self._document = document

    def lookup(self, ref: str) -> dict:
        if not ref.startswith("#/"):
            return {}
        node: Any = self._document
        for part in ref[2:].split("/"):
            node = node.get(part, {}) if isinstance(node, dict) else {}
        return node if isinstance(node, dict) else {}

    def resolve(self, node: Any, max_depth: int, depth: int = 0, hard_max: int = 8) -> Any:
        """Past max_depth, only required properties are followed, so trimming never loses one."""
        if isinstance(node, list):
            return [self.resolve(item, max_depth, depth, hard_max) for item in node]
        if not isinstance(node, dict):
            return node
        if "$ref" in node:
            target = self.lookup(node["$ref"])
            if depth >= hard_max:
                return _placeholder(target)
            if depth >= max_depth:
                target = _required_only(target)
                if target is None:
                    return _placeholder(self.lookup(node["$ref"]))
            return self.resolve(target, max_depth, depth + 1, hard_max)
        return {
            key: self.resolve(value, max_depth, depth, hard_max)
            for key, value in node.items()
            if key not in DROP_KEYS and not key.startswith("x-")
        }


def _required_only(target: dict) -> dict | None:
    required = target.get("required") or []
    props = target.get("properties") or {}
    if required and props:
        out = {k: v for k, v in target.items() if k != "properties"}
        out["properties"] = {name: props[name] for name in required if name in props}
        return out
    if any(target.get(key) for key in NESTED_LISTS) or target.get("type") == "array":
        return target
    return None


def _placeholder(target: dict) -> dict:
    out: dict = {"type": target.get("type", "object")}
    if target.get("description"):
        out["description"] = _cut(target["description"], 120)
    return out


def _cut(text: str, limit: int) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def trim(node: Any, desc_limit: int = 120, enum_limit: int = 20) -> Any:
    if isinstance(node, list):
        return [trim(item, desc_limit, enum_limit) for item in node]
    if not isinstance(node, dict):
        return node
    out: dict = {}
    required = list(node.get("required", []))
    for key, value in node.items():
        if key in DROP_KEYS or key.startswith("x-") or key in ("readOnly", "title"):
            continue
        if key == "description":
            out[key] = _cut(value, desc_limit)
        elif key == "enum" and isinstance(value, list) and len(value) > enum_limit:
            out[key] = value[:enum_limit]
            dropped = len(value) - enum_limit
            out["description"] = _cut(
                f"{node.get('description', '')} ({dropped} more values not listed)".strip(),
                desc_limit,
            )
        elif key == "properties" and isinstance(value, dict):
            out[key] = {
                name: trim(prop, desc_limit, enum_limit)
                for name, prop in value.items()
                if name in required or not (isinstance(prop, dict) and prop.get("readOnly"))
            }
        elif key == "required":
            continue
        elif key in NESTED_LISTS or key in ("items", "additionalProperties", "not"):
            out[key] = trim(value, desc_limit, enum_limit)
        else:
            out[key] = value
    if required:
        kept = set(out.get("properties", {})) if "properties" in out else set(required)
        out["required"] = [name for name in required if name in kept]
        if not out["required"]:
            out.pop("required")
    return out


def required_paths(schema: Any, prefix: str = "") -> set[str]:
    found: set[str] = set()
    if not isinstance(schema, dict):
        return found
    props = schema.get("properties", {})
    for name in schema.get("required", []):
        path = f"{prefix}.{name}" if prefix else name
        found.add(path)
        found |= required_paths(props.get(name, {}), path)
    for key in NESTED_LISTS:
        for sub in schema.get(key, []) or []:
            found |= required_paths(sub, prefix)
    return found
