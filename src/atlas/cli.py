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


@app.command()
def enrich() -> None:
    """Add a purpose and 5 example requests per tool, cached in data/enrichment.json."""
    from atlas.catalog import CatalogPaths
    from atlas.llm import build_chat_model
    from atlas.tools.enrich import Enricher
    from atlas.tools.spec import load_specs
    from atlas.tracing import tracing

    settings = get_settings()
    paths = CatalogPaths(settings)
    specs = load_specs(paths.tools)
    enricher = Enricher(
        build_chat_model(settings), paths.enrichment, settings.atlas_examples_per_tool
    )
    done: list[str] = []

    def progress(name: str) -> None:
        done.append(name)
        typer.echo(f"  [{len(done)}] {name}")

    with tracing(settings):
        cache = asyncio.run(enricher.run(specs, progress))
    typer.echo(f"enriched {len(done)} tools · {len(cache)} cached in {paths.enrichment}")


@app.command()
def index() -> None:
    """Rebuild the Qdrant tool collection from tools.json and enrichment.json."""
    from atlas.catalog import load_catalog
    from atlas.retrieval.factory import get_tool_index

    settings = get_settings()
    specs = load_catalog(settings)
    points = asyncio.run(get_tool_index(settings).rebuild(specs))
    collection = settings.atlas_tools_collection
    typer.echo(f"indexed {len(specs)} tools as {points} vectors → {collection}")


@app.command()
def search(query: str, k: int = typer.Option(8, help="How many tools to return.")) -> None:
    """Show the top-k tools for a request."""
    from atlas.retrieval.factory import get_tool_index

    for hit in asyncio.run(get_tool_index(get_settings()).search(query, k)):
        typer.echo(f"{hit.rank:>2}. {hit.score:.3f}  {hit.name}")


eval_app = typer.Typer(no_args_is_help=True, help="Run evaluations.")
app.add_typer(eval_app, name="eval")


@eval_app.command("retrieval")
def eval_retrieval(
    split: str = typer.Option("all", help="dev, test or all"),
    heads_only: bool = typer.Option(False, help="Search tool descriptions only, no examples."),
    check_baseline: bool = typer.Option(False, help="Fail if test Recall@8 drops below baseline."),
    save_baseline: bool = typer.Option(False, help="Store this run's test Recall@8 as baseline."),
) -> None:
    """R0: score retrieval alone, with no LLM."""
    from atlas.catalog import load_catalog
    from atlas.evals.cases import load_cases
    from atlas.evals.retrieval import BASELINE_PATH, run_retrieval, save_run
    from atlas.retrieval.factory import get_tool_index

    settings = get_settings()
    groups = {s.name: s.group for s in load_catalog(settings)}
    cases = load_cases(split=split)
    run = asyncio.run(run_retrieval(get_tool_index(settings), cases, groups, heads_only))
    config = {"embed_model": settings.atlas_embed_model, "split": split, "heads_only": heads_only}
    path = save_run(run, config, "r0-heads" if heads_only else "r0")

    keys = ["recall@3", "recall@5", "recall@8", "precision@5", "mrr", "ndcg@5"]
    typer.echo(f"{'':<14}{'n':>4} " + " ".join(f"{k:>11}" for k in keys))
    sections = {"all": run.summary, **run.by_split, **run.by_category}
    for name, row in sections.items():
        typer.echo(f"{name:<14}{row['n']:>4} " + " ".join(f"{row[k]:>11.3f}" for k in keys))
    misses = [c for c in run.cases if c["recall@8"] < 1]
    typer.echo(f"\nmisses at k=8: {len(misses)}")
    for c in misses:
        typer.echo(f"  [{c['split']}] {c['id']}: want {c['expected']} got {c['top'][:5]}")
    typer.echo(f"results: {path}")

    test_recall = run.by_split.get("test", {}).get("recall@8")
    if save_baseline and test_recall is not None:
        BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
        BASELINE_PATH.write_text(json.dumps({"test_recall@8": test_recall}, indent=2) + "\n")
        typer.echo(f"baseline saved: test recall@8 = {test_recall:.4f}")
    if check_baseline:
        baseline = json.loads(BASELINE_PATH.read_text())["test_recall@8"]
        if test_recall is None or test_recall + 1e-9 < baseline:
            typer.secho(f"test recall@8 {test_recall} < baseline {baseline}", fg="red", err=True)
            raise typer.Exit(code=1)
        typer.echo(f"baseline ok: {test_recall:.4f} >= {baseline:.4f}")


@eval_app.command("leakage")
def eval_leakage() -> None:
    """Flag cases that are near-copies of a stored example request."""
    from atlas.catalog import load_catalog
    from atlas.evals.cases import load_cases
    from atlas.evals.retrieval import LEAKAGE_THRESHOLD, leakage
    from atlas.retrieval.factory import get_embedder

    settings = get_settings()
    flagged = leakage(
        load_cases(), load_catalog(settings), get_embedder(settings.atlas_embed_model)
    )
    typer.echo(f"cases above {LEAKAGE_THRESHOLD} similarity to a stored example: {len(flagged)}")
    for case_id, example, score in flagged:
        typer.echo(f"  {case_id} ({score:.3f}) ~ {example}")
    if flagged:
        raise typer.Exit(code=1)


@app.command()
def kb() -> None:
    """Rebuild the Qdrant knowledge-base collection from kb/*.md."""
    from pathlib import Path

    from atlas.retrieval.factory import get_embedder, make_qdrant_client
    from atlas.tools.rag import KnowledgeBase, load_chunks

    settings = get_settings()
    knowledge_base = KnowledgeBase(
        make_qdrant_client(settings),
        get_embedder(settings.atlas_embed_model),
        settings.atlas_kb_collection,
    )
    count = asyncio.run(knowledge_base.rebuild(load_chunks(Path("kb"))))
    typer.echo(f"indexed {count} handbook sections → {settings.atlas_kb_collection}")


async def _console_approver(requests: list[dict]) -> list[dict]:
    decisions = []
    for request in requests:
        typer.secho(f"\n  {request['name']} wants to run with:", fg=typer.colors.YELLOW)
        typer.echo("  " + json.dumps(request["args"], indent=2).replace("\n", "\n  "))
        approved = typer.confirm("  Approve this change?", default=False)
        decisions.append({"type": "approve" if approved else "reject"})
    return decisions


async def _yes(requests: list[dict]) -> list[dict]:
    return [{"type": "approve"} for _ in requests]


def _print_turn(result) -> None:
    for call in result.tool_calls:
        mark = "ok" if call.ok else f"status {call.status}"
        typer.secho(f"  · {call.name} ({mark})", fg=typer.colors.BRIGHT_BLACK)
    if result.error:
        typer.secho(f"  error: {result.error}", fg=typer.colors.RED)
    typer.echo(f"\n{result.answer}\n")
    if result.trace_url:
        typer.secho(f"  trace: {result.trace_url}\n", fg=typer.colors.BRIGHT_BLACK)


def _agent_session(settings):
    from atlas.agent.build import AgentOptions, build_atlas
    from atlas.agent.factory import make_deps

    deps = make_deps(settings)
    options = AgentOptions(k=settings.atlas_k, approve_writes=True, today=settings.atlas_today)
    writes = {s.name for s in deps.specs if s.access == "write"}
    return build_atlas(deps, options), writes, deps.runlog


@app.command()
def ask(
    message: str,
    yes: bool = typer.Option(False, "--yes", help="Approve every change without asking."),
) -> None:
    """Send one message to Atlas."""
    from uuid import uuid4

    from atlas.agent.turn import run_turn
    from atlas.tracing import tracing

    settings = get_settings()
    agent, writes, runlog = _agent_session(settings)
    approver = _yes if yes else _console_approver
    with tracing(settings):
        result = asyncio.run(run_turn(agent, message, uuid4().hex, writes, approver, runlog))
    _print_turn(result)


@app.command()
def chat() -> None:
    """Chat with Atlas. Changes to your account ask for approval first."""
    from uuid import uuid4

    from atlas.agent.turn import run_turn
    from atlas.tracing import tracing

    settings = get_settings()
    agent, writes, runlog = _agent_session(settings)
    thread_id = uuid4().hex
    typer.echo("Atlas is ready. Type 'exit' to quit.\n")

    async def loop() -> None:
        while True:
            message = typer.prompt("you").strip()
            if message.lower() in {"exit", "quit"}:
                return
            result = await run_turn(agent, message, thread_id, writes, _console_approver, runlog)
            _print_turn(result)

    with tracing(settings):
        asyncio.run(loop())


@eval_app.command("agent")
def eval_agent(
    split: str = typer.Option("test", help="dev, test or all"),
    limit: int = typer.Option(0, help="Only the first N cases (0 = all)."),
    concurrency: int = typer.Option(4, help="Cases in flight at once."),
) -> None:
    """Run Atlas once per case: tool execution success, task completion, p95 latency, cost."""
    from atlas.evals.agent_run import CaseRunner, run_cases, save_agent_run, score_outputs
    from atlas.evals.cases import load_cases
    from atlas.tracing import tracing

    settings = get_settings()
    cases = load_cases(split=split)
    if limit:
        cases = cases[:limit]
    runner = CaseRunner(settings)
    with tracing(settings):
        outputs = asyncio.run(run_cases(runner, cases, concurrency))
    report = score_outputs(cases, outputs, runner.writes, settings)
    path = save_agent_run(report, {"split": split, "model": settings.atlas_model})

    keys = ["task_completion", "tool_execution_success", "p95_latency_s", "cost_per_task_usd"]
    typer.echo(f"{'':<10}{'n':>4} " + " ".join(f"{k[:16]:>17}" for k in keys))
    sections = {"all": report["summary"], **report["by_category"]}
    for section, row in sections.items():
        cells = " ".join(f"{'—' if row.get(k) is None else row[k]:>17}" for k in keys)
        typer.echo(f"{section:<10}{row['n']:>4} " + cells)
    missed = [c for c in report["cases"] if not c["task_completed"] and c["status"] != "error"]
    typer.echo(f"\nnot completed: {len(missed)}")
    for c in missed:
        typer.echo(f"  {c['id']} ({c['status']}): {c['calls'][:6]}")
    typer.echo(f"results: {path}")
    if report["errors"]:
        kinds = sorted({e["error"][:120] for e in report["errors"]})
        typer.secho(
            f"\n{len(report['errors'])} cases hit errors and are left out of the scores:",
            fg="red",
            err=True,
        )
        for kind in kinds[:5]:
            typer.secho(f"  {kind}", fg="red", err=True)
        raise typer.Exit(code=1)
