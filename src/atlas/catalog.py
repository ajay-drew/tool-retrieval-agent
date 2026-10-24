import json
from pathlib import Path

from atlas.config import Settings
from atlas.tools.spec import ToolSpec, load_specs


class CatalogPaths:
    def __init__(self, settings: Settings):
        data = settings.atlas_data_dir
        self.tools = data / "tools.json"
        self.full_schemas = data / "full_schemas.json"
        self.enrichment = data / "enrichment.json"


def load_catalog(settings: Settings) -> list[ToolSpec]:
    paths = CatalogPaths(settings)
    specs = load_specs(paths.tools)
    enrichment = _read_json(paths.enrichment)
    for spec in specs:
        entry = enrichment.get(spec.name)
        if entry:
            spec.purpose = entry["purpose"]
            spec.examples = entry["examples"]
    return specs


def load_full_schemas(settings: Settings) -> dict[str, dict]:
    return _read_json(CatalogPaths(settings).full_schemas)


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text()) if path.exists() else {}
