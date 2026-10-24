import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


class ToolSpec(BaseModel):
    name: str
    original_id: str
    service: str
    group: str
    method: str
    path: str
    summary: str
    description: str
    access: Literal["read", "write"]
    params_schema: dict
    full_schema_ref: str
    purpose: str = ""
    examples: list[str] = Field(default_factory=list)
    keywords: str = ""
    raw_tokens: int = 0
    trimmed_tokens: int = 0


def save_specs(specs: list[ToolSpec], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([s.model_dump() for s in specs], indent=2))


def load_specs(path: Path) -> list[ToolSpec]:
    return [ToolSpec.model_validate(item) for item in json.loads(path.read_text())]
