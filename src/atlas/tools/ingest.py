import html
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from jsonschema import Draft202012Validator

from atlas.tools.schema import RefResolver, approx_tokens, trim
from atlas.tools.spec import ToolSpec

HTTP_METHODS = ("get", "post", "put", "patch", "delete")
NAME_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
HTML_TAG = re.compile(r"<[^>]+>")
TRIM_LEVELS = ((3, 120), (2, 120), (2, 60))
OVER_BUDGET_REASON = (
    "still over budget at the depth-2 floor; trimming deeper removes fields the call needs"
)
FULL_DEPTH = 8


@dataclass(frozen=True)
class IngestResult:
    specs: list[ToolSpec]
    full_schemas: dict[str, dict]


def safe_name(operation_id: str, service: str, prefix_service: bool) -> str:
    base = re.sub(r"[^a-zA-Z0-9_-]", "_", operation_id)
    name = f"{service}__{base}" if prefix_service else base
    if not NAME_PATTERN.match(name):
        raise ValueError(f"tool name {name!r} does not match {NAME_PATTERN.pattern}")
    return name


def _plain(text: str) -> str:
    return " ".join(html.unescape(HTML_TAG.sub(" ", text or "")).split())


def _description(op: dict) -> str:
    summary = _plain(op.get("summary", ""))
    body = _plain(op.get("description", ""))
    text = body if body.lower().startswith(summary.lower()) else f"{summary}. {body}".strip(". ")
    return text if len(text) <= 300 else text[:299].rstrip() + "…"


def _param_section(params: list[dict], location: str) -> dict | None:
    chosen = [p for p in params if p.get("in") == location]
    if not chosen:
        return None
    section: dict = {"type": "object", "properties": {}}
    required = []
    for p in chosen:
        schema = dict(p.get("schema", {}))
        if p.get("description") and "description" not in schema:
            schema["description"] = p["description"]
        section["properties"][p["name"]] = schema
        if p.get("required") or location == "path":
            required.append(p["name"])
    if required:
        section["required"] = required
    return section


def _body_schema(request_body: dict) -> dict | None:
    content = request_body.get("content", {})
    if not content:
        return None
    media = content.get("application/json") or next(iter(content.values()))
    return media.get("schema")


def build_params_schema(item: dict, op: dict, resolver: RefResolver, depth: int) -> dict:
    params = [
        resolver.resolve(p, depth) for p in item.get("parameters", []) + op.get("parameters", [])
    ]
    schema: dict = {"type": "object", "properties": {}}
    required: list[str] = []
    for location in ("path", "query"):
        section = _param_section(params, location)
        if section:
            schema["properties"][location] = section
            if section.get("required"):
                required.append(location)
    request_body = resolver.resolve(op.get("requestBody", {}), depth)
    body = _body_schema(request_body) if request_body else None
    if body is not None:
        schema["properties"]["body"] = resolver.resolve(body, depth)
        if request_body.get("required"):
            required.append("body")
    if required:
        schema["required"] = required
    return schema


def trim_to_budget(item: dict, op: dict, resolver: RefResolver, token_limit: int) -> dict:
    schema: dict = {}
    for depth, desc_limit in TRIM_LEVELS:
        schema = trim(build_params_schema(item, op, resolver, depth), desc_limit=desc_limit)
        if approx_tokens(schema) <= token_limit:
            break
    return schema


def ingest_file(
    path: Path, service: str, prefix_service: bool, token_limit: int = 1500
) -> IngestResult:
    document = json.loads(path.read_text())
    resolver = RefResolver(document)
    specs: list[ToolSpec] = []
    full_schemas: dict[str, dict] = {}
    for route, item in document.get("paths", {}).items():
        for method in HTTP_METHODS:
            op = item.get(method)
            if not op:
                continue
            name = safe_name(op["operationId"], service, prefix_service)
            full = build_params_schema(item, op, resolver, FULL_DEPTH)
            trimmed = trim_to_budget(item, op, resolver, token_limit)
            Draft202012Validator.check_schema(trimmed)
            full_schemas[name] = full
            specs.append(
                ToolSpec(
                    name=name,
                    original_id=op["operationId"],
                    service=service,
                    group=path.stem,
                    method=method.upper(),
                    path=route,
                    summary=_plain(op.get("summary", "")),
                    description=_description(op),
                    access="read" if method == "get" else "write",
                    params_schema=trimmed,
                    full_schema_ref=name,
                    raw_tokens=approx_tokens(full),
                    trimmed_tokens=approx_tokens(trimmed),
                )
            )
    return IngestResult(specs=specs, full_schemas=full_schemas)


def ingest_service(
    spec_dir: Path, service: str, prefix_service: bool = False, token_limit: int = 1500
) -> IngestResult:
    specs: list[ToolSpec] = []
    full: dict[str, dict] = {}
    for path in sorted(spec_dir.glob("*.json")):
        result = ingest_file(path, service, prefix_service, token_limit)
        specs.extend(result.specs)
        full.update(result.full_schemas)
    return IngestResult(specs=specs, full_schemas=full)


def ensure_unique(specs: Iterable[ToolSpec]) -> None:
    seen: set[str] = set()
    for spec in specs:
        if spec.name in seen:
            raise ValueError(f"duplicate tool name {spec.name!r}")
        seen.add(spec.name)


def size_report(specs: list[ToolSpec], limit: int) -> str:
    rows = sorted(specs, key=lambda s: s.trimmed_tokens, reverse=True)
    total_raw = sum(s.raw_tokens for s in specs)
    total_trim = sum(s.trimmed_tokens for s in specs)
    lines = [
        "# Tool definition sizes",
        "",
        "Approximate tokens (JSON characters / 4) for each tool's input schema.",
        "",
        f"- Tools: {len(specs)}",
        f"- All tools, untrimmed: {total_raw:,}",
        f"- All tools, trimmed: {total_trim:,}",
        f"- Over the {limit:,}-token limit after trimming: "
        f"{sum(1 for s in specs if s.trimmed_tokens > limit)}",
        "",
        f"  Reason: {OVER_BUDGET_REASON}.",
        "",
        "| Tool | Group | Untrimmed | Trimmed | Over budget |",
        "|---|---|---:|---:|---|",
    ]
    lines += [
        f"| `{s.name}` | {s.group} | {s.raw_tokens:,} | {s.trimmed_tokens:,} | "
        f"{'yes' if s.trimmed_tokens > limit else ''} |"
        for s in rows
    ]
    return "\n".join(lines) + "\n"
