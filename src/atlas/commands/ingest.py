import json
from pathlib import Path

from atlas.catalog import CatalogPaths
from atlas.config import Settings
from atlas.tools.ingest import ensure_unique, ingest_service, size_report
from atlas.tools.spec import ToolSpec, save_specs

REPORT_PATH = Path("reports/ingest_sizes.md")


def run_ingest(settings: Settings) -> list[ToolSpec]:
    prefix = len(settings.atlas_services) > 1
    specs: list[ToolSpec] = []
    full: dict[str, dict] = {}
    for service in settings.atlas_services:
        result = ingest_service(
            settings.atlas_specs_dir / service, service, prefix, settings.atlas_max_tool_tokens
        )
        specs.extend(result.specs)
        full.update(result.full_schemas)
    ensure_unique(specs)
    paths = CatalogPaths(settings)
    save_specs(specs, paths.tools)
    paths.full_schemas.write_text(json.dumps(full))
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(size_report(specs, settings.atlas_max_tool_tokens))
    return specs
