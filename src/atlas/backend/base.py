from dataclasses import dataclass, field
from typing import Protocol

from atlas.tools.spec import ToolSpec


class BackendTransientError(RuntimeError):
    def __init__(self, status: int, message: str = "temporary backend failure"):
        super().__init__(f"{status}: {message}")
        self.status = status


@dataclass
class BackendResult:
    status: int
    body: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300


class Backend(Protocol):
    async def call(self, spec: ToolSpec, args: dict) -> BackendResult: ...

    def reset(self) -> None: ...
