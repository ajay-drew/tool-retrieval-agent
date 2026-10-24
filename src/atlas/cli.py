import asyncio
import json

import typer

from atlas.config import get_settings
from atlas.llm import MissingKeyError
from atlas.smoke import run_smoke

app = typer.Typer(no_args_is_help=True, add_completion=False)


@app.callback()
def main() -> None:
    """Atlas: a tool-retrieval agent."""


@app.command()
def smoke() -> None:
    """Check that the model makes a tool call and LangSmith records the trace."""
    settings = get_settings()
    try:
        result = asyncio.run(run_smoke(settings))
    except MissingKeyError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from exc

    for call in result.tool_calls:
        typer.echo(f"tool call: {call['name']}({json.dumps(call['args'])})")
    if result.trace_url:
        typer.echo(f"trace: {result.trace_url}")
    else:
        typer.echo("trace: off (set LANGSMITH_API_KEY to record one)")

    if not result.tool_calls:
        typer.secho("The model answered without calling the tool.", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)


@app.command()
def ingest() -> None:
    """Parse the OpenAPI specs into data/tools.json and write the size report."""
    from atlas.commands.ingest import REPORT_PATH, run_ingest

    settings = get_settings()
    specs = run_ingest(settings)
    over = [s for s in specs if s.trimmed_tokens > settings.atlas_max_tool_tokens]
    raw = sum(s.raw_tokens for s in specs)
    trimmed = sum(s.trimmed_tokens for s in specs)
    typer.echo(f"{len(specs)} tools · untrimmed ~{raw:,} tokens · trimmed ~{trimmed:,} tokens")
    typer.echo(f"over {settings.atlas_max_tool_tokens:,} tokens: {len(over)}")
    for spec in over:
        typer.echo(f"  {spec.name}: {spec.trimmed_tokens:,}")
    typer.echo(f"report: {REPORT_PATH}")
