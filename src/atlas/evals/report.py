import html
import json
from pathlib import Path

from atlas.evals.retrieval import RESULTS_DIR

REPORT_PATH = Path("evals/report.html")
README_PATH = Path("README.md")
START, END = "<!-- results:start -->", "<!-- results:end -->"

RUN_ORDER = [
    ("r1-all", "All 115 tools in every call (trimmed)"),
    ("r1-untrimmed", "All 115 tools, untrimmed schemas (30-case sample)"),
    ("r2", "Atlas: top 8 by retrieval + find_tools"),
    ("r3-k3", "Atlas, k = 3"),
    ("r3-k5", "Atlas, k = 5"),
    ("r3-k12", "Atlas, k = 12"),
    ("r3-heads", "Atlas, descriptions only (no example requests)"),
    ("r3-nofind", "Atlas without find_tools"),
    ("r3-llmselect", "LangChain LLMToolSelector (LLM picks 8)"),
]
AGENT_COLS = [
    ("task_completion", "Task completion", "pct"),
    ("exposure_recall", "Exposure recall", "pct"),
    ("tool_execution_success", "Tool exec. success", "pct"),
    ("first_call_correct", "First call correct", "pct"),
    ("p95_latency_s", "p95 latency (s)", "num"),
    ("cost_per_task_usd", "Cost / task ($)", "cost"),
    ("mean_tokens_in", "Input tokens / task", "int"),
    ("max_tools_shown", "Max tools shown", "int"),
]
R0_COLS = ["recall@3", "recall@5", "recall@8", "precision@5", "mrr", "ndcg@5"]


def latest_results() -> dict[str, dict]:
    found: dict[str, dict] = {}
    for path in sorted(RESULTS_DIR.glob("*.json")):
        data = json.loads(path.read_text())
        name = data.get("run")
        if name == "r0" and data.get("config", {}).get("split") != "all":
            continue
        found[name] = {**data, "_file": path.name}
    return found


def _fmt(value, kind: str) -> str:
    if value is None:
        return "—"
    if kind == "pct":
        return f"{value * 100:.1f}%"
    if kind == "cost":
        return f"{value:.4f}"
    if kind == "int":
        return f"{value:,.0f}"
    return f"{value:.1f}" if isinstance(value, float) else str(value)


def agent_rows(results: dict, split: str) -> list[tuple[str, str, dict]]:
    rows = []
    for name, label in RUN_ORDER:
        if name not in results:
            continue
        data = results[name]
        section = data["summary"] if split == "all" else data["by_split"].get(split)
        if section:
            rows.append((name, label, section))
    return rows


def markdown_table(results: dict, split: str = "test") -> str:
    cols = [c for c in AGENT_COLS if c[0] != "first_call_correct"]
    head = "| Run | n | " + " | ".join(c[1] for c in cols) + " |"
    sep = "|---|---:|" + "---:|" * len(cols)
    lines = [head, sep]
    for name, label, row in agent_rows(results, split):
        cells = " | ".join(_fmt(row.get(key), kind) for key, _, kind in cols)
        lines.append(f"| {label} (`{name}`) | {row['n']} | {cells} |")
    return "\n".join(lines)


def r0_markdown(results: dict) -> str:
    r0 = results.get("r0")
    if not r0:
        return ""
    lines = ["| Split | n | " + " | ".join(R0_COLS) + " |", "|---|---:|" + "---:|" * len(R0_COLS)]
    for split in ("dev", "test"):
        row = r0["by_split"].get(split)
        if row:
            cells = " | ".join(f"{row[k]:.3f}" for k in R0_COLS)
            lines.append(f"| {split} | {row['n']} | {cells} |")
    return "\n".join(lines)


def _bar_chart(title: str, items: list[tuple[str, float]], unit: str, fmt) -> str:
    if not items:
        return ""
    width, bar_h, gap, left = 640, 22, 10, 230
    top = max(v for _, v in items) or 1
    height = len(items) * (bar_h + gap) + 30
    bars = []
    for i, (label, value) in enumerate(items):
        y = 20 + i * (bar_h + gap)
        w = (width - left - 90) * value / top
        bars.append(
            f'<text x="{left - 8}" y="{y + 15}" text-anchor="end" class="lbl">'
            f"{html.escape(label)}</text>"
            f'<rect x="{left}" y="{y}" width="{w:.1f}" height="{bar_h}" rx="3" class="bar"/>'
            f'<text x="{left + w + 6:.1f}" y="{y + 15}" class="val">{fmt(value)}{unit}</text>'
        )
    return (
        f"<figure><figcaption>{html.escape(title)}</figcaption>"
        f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="{html.escape(title)}">'
        + "".join(bars)
        + "</svg></figure>"
    )


def build_html(results: dict) -> str:
    test_rows = agent_rows(results, "test")
    charts = [
        _bar_chart(
            "Task completion, test split",
            [(label, row["task_completion"] or 0) for _, label, row in test_rows],
            "%",
            lambda v: f"{v * 100:.1f}",
        ),
        _bar_chart(
            "Input tokens per task, test split",
            [(label, row["mean_tokens_in"] or 0) for _, label, row in test_rows],
            "",
            lambda v: f"{v:,.0f}",
        ),
    ]

    def table(split: str) -> str:
        head = "".join(f"<th>{html.escape(c[1])}</th>" for c in AGENT_COLS)
        body = []
        for name, label, row in agent_rows(results, split):
            cells = "".join(f"<td>{_fmt(row.get(k), kind)}</td>" for k, _, kind in AGENT_COLS)
            body.append(
                f"<tr><th>{html.escape(label)}<br><code>{name}</code></th>"
                f"<td>{row['n']}</td>{cells}</tr>"
            )
        return f"<table><tr><th>Run</th><th>n</th>{head}</tr>{''.join(body)}</table>"

    r2 = results.get("r2")
    category = ""
    failures = ""
    if r2:
        cat_rows = "".join(
            f"<tr><th>{c}</th><td>{row['n']}</td><td>{_fmt(row['task_completion'], 'pct')}</td>"
            f"<td>{_fmt(row['exposure_recall'], 'pct')}</td>"
            f"<td>{_fmt(row['tool_execution_success'], 'pct')}</td></tr>"
            for c, row in r2["by_category"].items()
        )
        category = (
            "<h2>Atlas (r2) by category</h2><table><tr><th>Category</th><th>n</th>"
            "<th>Task completion</th><th>Exposure recall</th><th>Tool exec. success</th></tr>"
            f"{cat_rows}</table>"
        )
        missed = [c for c in r2["cases"] if not c["task_completed"]]
        items = "".join(
            f"<li><b>{html.escape(c['id'])}</b> ({c['split']}, {c['category']}, {c['status']}) "
            f"{html.escape(c['query'])}<br><small>calls: "
            f"{html.escape(', '.join(f'{n} {s}' for n, s in c['calls']) or 'none')}"
            + (
                f' · <a href="{html.escape(c["trace_url"])}">trace</a>'
                if c.get("trace_url")
                else ""
            )
            + "</small></li>"
            for c in missed
        )
        failures = f"<h2>Atlas (r2) cases not completed ({len(missed)})</h2><ul>{items}</ul>"

    r0 = results.get("r0")
    r0_html = ""
    if r0:
        rows = "".join(
            f"<tr><th>{split}</th><td>{row['n']}</td>"
            + "".join(f"<td>{row[k]:.3f}</td>" for k in R0_COLS)
            + "</tr>"
            for split, row in r0["by_split"].items()
        )
        head = "".join(f"<th>{k}</th>" for k in R0_COLS)
        r0_html = (
            "<h2>R0: retrieval only (no LLM)</h2>"
            f"<table><tr><th>Split</th><th>n</th>{head}</tr>{rows}</table>"
        )

    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Atlas eval report</title>
<style>
:root{{--bg:#f6f7f9;--fg:#17202b;--muted:#5b6675;--line:#dde2e8;--accent:#1f6f78;--surface:#fff}}
@media (prefers-color-scheme:dark){{:root{{--bg:#11161c;--fg:#e4e9ef;--muted:#9aa6b4;
--line:#2a3542;--accent:#5cc0c8;--surface:#18202a}}}}
body{{background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif;margin:0;
padding:32px max(16px,4vw)}}
main{{max-width:1100px;margin:auto}} h1,h2{{line-height:1.2}}
table{{border-collapse:collapse;width:100%;background:var(--surface);margin:12px 0 28px;
font-variant-numeric:tabular-nums}}
th,td{{border-bottom:1px solid var(--line);padding:7px 10px;text-align:right;vertical-align:top}}
th:first-child{{text-align:left}} td{{white-space:nowrap}}
code{{color:var(--muted);font-size:.85em}} small{{color:var(--muted)}} li{{margin-bottom:8px}}
figure{{margin:12px 0 24px}} figcaption{{font-weight:600;margin-bottom:6px}}
svg{{width:100%;max-width:760px}} .bar{{fill:var(--accent)}}
.lbl,.val{{fill:var(--fg);font-size:12px}} .val{{fill:var(--muted)}}
.scroll{{overflow-x:auto}} a{{color:var(--accent)}}
</style></head><body><main>
<h1>Atlas eval report</h1>
<p>Model: {html.escape(str(r2.get("model") if r2 else ""))} · cases: evals/cases.jsonl
(60 dev used for tuning, 91 held-out test) · mock PayPal backend, eval date 2026-10-24.</p>
{"".join(charts)}
<h2>Full agent, test split (held out)</h2><div class="scroll">{table("test")}</div>
<h2>Full agent, all cases</h2><div class="scroll">{table("all")}</div>
{r0_html}{category}{failures}
</main></body></html>"""


def update_readme(results: dict) -> bool:
    if not README_PATH.exists():
        return False
    text = README_PATH.read_text()
    if START not in text or END not in text:
        return False
    block = (
        f"{START}\n\n**Full agent, held-out test split**\n\n{markdown_table(results)}\n\n"
        f"**Retrieval only (R0, no LLM)**\n\n{r0_markdown(results)}\n\n{END}"
    )
    before, rest = text.split(START, 1)
    after = rest.split(END, 1)[1]
    README_PATH.write_text(before + block + after)
    return True


def write_report() -> tuple[Path, bool]:
    results = latest_results()
    REPORT_PATH.write_text(build_html(results))
    return REPORT_PATH, update_readme(results)
