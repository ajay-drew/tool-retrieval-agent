import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

ALWAYS_ON = ("rag_search", "system_search", "find_tools")
CASES_PATH = Path("evals/cases.jsonl")


class Case(BaseModel):
    id: str
    split: Literal["dev", "test"]
    category: Literal["single", "multi", "rag", "system", "clarify"]
    query: str
    expected_tools: list[str] = Field(default_factory=list)
    ordered: bool = False
    alternatives: dict[str, list[str]] = Field(default_factory=dict)
    arg_checks: dict[str, dict] = Field(default_factory=dict)
    expect_question: bool = False
    answer_contains: list[str] = Field(default_factory=list)

    @property
    def indexed_tools(self) -> list[str]:
        return [t for t in self.expected_tools if t not in ALWAYS_ON]

    def accepted(self, tool: str) -> set[str]:
        return {tool, *self.alternatives.get(tool, [])}


def load_cases(path: Path = CASES_PATH, split: str = "all") -> list[Case]:
    lines = [line for line in path.read_text().splitlines() if line]
    cases = [Case.model_validate(json.loads(line)) for line in lines]
    return cases if split == "all" else [c for c in cases if c.split == split]
