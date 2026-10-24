import json
from pathlib import Path


class RunLog:
    def __init__(self, path: Path):
        self._path = path

    def append(self, row: dict) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a") as f:
            f.write(json.dumps(row) + "\n")

    def recent(self, n: int = 5) -> list[dict]:
        if not self._path.exists():
            return []
        lines = [line for line in self._path.read_text().splitlines() if line]
        return [json.loads(line) for line in reversed(lines[-n:])]
