import json

from jsonschema import Draft202012Validator
from langchain_core.tools import StructuredTool

from atlas.backend.base import Backend
from atlas.tools.spec import ToolSpec

MAX_LIST_ITEMS = 10


def _shrink(body: object) -> object:
    if isinstance(body, dict):
        return {k: _shrink(v) for k, v in body.items()}
    if isinstance(body, list) and len(body) > MAX_LIST_ITEMS:
        return [_shrink(v) for v in body[:MAX_LIST_ITEMS]] + [
            f"... {len(body) - MAX_LIST_ITEMS} more"
        ]
    if isinstance(body, list):
        return [_shrink(v) for v in body]
    return body


def tool_description(spec: ToolSpec) -> str:
    text = f"{spec.summary}. {spec.purpose}".strip(". ") + "."
    if spec.access == "write":
        text += " Changes data."
    return text[:1000]


def make_tool(spec: ToolSpec, backend: Backend) -> StructuredTool:
    validator = Draft202012Validator(spec.params_schema)

    async def run(**kwargs: object) -> str:
        errors = sorted(validator.iter_errors(kwargs), key=lambda e: e.json_path)
        if errors:
            details = [{"field": e.json_path, "issue": e.message[:200]} for e in errors[:5]]
            return json.dumps({"status": 400, "error": "invalid_input", "details": details})
        result = await backend.call(spec, kwargs)
        return json.dumps({"status": result.status, "body": _shrink(result.body)})

    return StructuredTool(
        name=spec.name,
        description=tool_description(spec),
        args_schema=spec.params_schema,
        coroutine=run,
        metadata={"access": spec.access, "group": spec.group, "service": spec.service},
    )


def build_tools(specs: list[ToolSpec], backend: Backend) -> list[StructuredTool]:
    return [make_tool(spec, backend) for spec in specs]
