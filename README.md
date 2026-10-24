# Atlas

A chat agent that stays accurate with 100+ API tools. On every model call, Atlas searches its tool catalog and gives the model only the tools that match the request, instead of all of them. Phase 1 uses PayPal's 115 REST operations plus two extra tools (knowledge-base search and system search), and an eval harness measures how well it picks tools and fills in their inputs.

Built on LangChain `create_agent`, DeepSeek v4-flash through OpenRouter, local bge-small embeddings and Qdrant, with LangSmith for tracing and evals.

## The problem

Sending every tool definition with every request doesn't scale. PayPal's 115 operations come to about **369k tokens** as raw OpenAPI schemas, and about 57k even after trimming. Accuracy also drops as near-identical tools (`invoices_list`, `invoices_search-invoices`, `invoices_get`) compete for the model's attention. At 500 or 2,000 tools, sending everything stops being possible at all.

## How Atlas works

```mermaid
flowchart LR
  subgraph Setup["Once, at setup"]
    S[OpenAPI specs] --> I[ingest + trim] --> E[enrich: purpose + 5 example requests] --> X[bge-small] --> Q[(Qdrant)]
  end
  subgraph Turn["Every model call (LangChain create_agent)"]
    U[user message] --> M[ToolRetrievalMiddleware: top 8 + 3 always-on]
    Q -.grouped search.-> M
    M --> L[DeepSeek v4-flash]
    L -- tool call --> H[approval pause for writes] --> T[tools]
    T --> M
    L -- answer --> R[reply + run log]
  end
  T --> P[Mock PayPal]
  T --> K[rag_search]
  T --> Y[system_search]
  T --> F[find_tools]
```

1. **Ingest** turns each OpenAPI operation into a tool. It resolves `$ref`s to depth 3, drops headers, read-only fields and examples, and trims harder (down to a depth-2 floor) when a tool is over 1,500 tokens. Required fields are never dropped, and a test proves it.
2. **Enrich** has DeepSeek write a one-line purpose and 5 example requests per tool: 3 direct requests and 2 questions that need the tool's data. This closes the gap between how people talk ("what did I sell last month?") and how APIs are named (`search_get`).
3. **Index**: each tool is stored as about 6 vectors in Qdrant (its description plus each example). Grouped search returns ranked *tools*, each scored by its best-matching vector.
4. **Retrieve per model call**: `ToolRetrievalMiddleware` searches with the last two user messages and swaps the request's tool list for the top 8 plus 3 always-on tools: `rag_search`, `system_search` and `find_tools`.
5. **`find_tools`** covers multi-step requests. When the next step needs a tool that wasn't retrieved (create, then *send*), the model searches the catalog itself, and the matches become callable on its next call.
6. **Safety**: write tools pause for approval in chat. Inputs are checked against the tool's schema before anything runs, and errors go back to the model once so it can correct itself.

## Design choices and trade-offs

- **Single agent with retrieval, not multi-agent.** A supervisor routing to domain sub-agents adds a model hop to every request. A wrong handoff can't be recovered, and someone has to draw the domain lines by hand. Retrieval scales by adding vectors, and `find_tools` recovers from a miss inside the same run. Multi-agent is a phase-2 comparison.
- **LangChain `create_agent` middleware.** The `wrap_model_call` hook can swap the tool list on every model call, which is exactly what retrieval needs. The approval pause, retries and call limits come built in. LangChain also ships an LLM-based tool picker (`LLMToolSelectorMiddleware`), which the evals compare against.
- **Qdrant with grouped search.** One result per tool, from several vectors per tool, with no post-processing. Filters (service, description-only) are payload filters.
- **bge-small, dense only.** On the dev split, bge-base and 10 examples per tool moved results by about one case (noise). Hybrid dense + BM25 was worse on every setup tried, losing 0.05–0.11 Recall@8. See [reports/r0_tuning.md](reports/r0_tuning.md).
- **Mock PayPal.** Generic REST routing with PayPal behaviour as data (`seed.json`), so evals are repeatable and need no sandbox account. Every one of the 115 tools passes a minimal valid call in the tests.

## Quickstart

```bash
uv sync
docker compose up -d          # Qdrant on :6333
cp .env.example .env          # add OPENROUTER_API_KEY and (optional) LANGSMITH_API_KEY
uv run atlas ingest           # specs → data/tools.json
uv run atlas enrich           # purposes + example requests (cached in data/enrichment.json)
uv run atlas index            # tool vectors → Qdrant
uv run atlas kb               # handbook → Qdrant
uv run atlas chat             # or: uv run atlas ask "Is there a dispute open from user_123?"
```

`data/enrichment.json` is committed, so `atlas enrich` is a no-op unless the specs change.

## Evals

```bash
uv run atlas eval retrieval            # Recall@k, Precision@k, MRR, nDCG@k; no LLM, about 10 s
uv run atlas eval leakage              # cases too close to stored example requests
uv run atlas eval agent                # one Atlas run per test case: tool execution success, task completion, p95 latency, cost
```

- **151 hand-written cases:** 81 single-tool, 30 multi-step, 15 knowledge-base, 10 system and 15 that should get a question back. They are split 60 **dev** (the only cases used for tuning) and 91 **test** (held out, reported below).
- **Retrieval (no LLM):** Recall@k, Precision@k, MRR and nDCG@k at k = 3, 5, 8, 10. CI runs it on every push against a committed baseline.
- **Agent run:** tool execution success, task completion, p95 latency and cost per task. Each case runs against a fresh mock, and its LangSmith trace link is saved with the results. Runs that hit an API error are left out of the scores and flagged.

## Results

**Retrieval only (held-out test split, 63 cases that need an indexed tool)**

| Recall@3 | Recall@5 | Recall@8 | Precision@5 | MRR | nDCG@5 |
|---:|---:|---:|---:|---:|---:|
| 0.778 | 0.857 | 0.921 | 0.213 | 0.743 | 0.745 |

Precision@5 is capped at 0.2 on single-tool cases (one right answer in five slots), so it compares setups rather than meeting a target. Most Recall@8 misses are multi-step requests, where one query has to surface two tools; inside the agent `find_tools` picks up the second one.

**Agent run:** pending a model key with credits (see [docs/decisions.md](docs/decisions.md), problem 21).

## Layout

```
specs/paypal/        PayPal OpenAPI specs (Apache-2.0, commit 90e8041) + read-only overrides
kb/                  handbook for rag_search (fictional merchant)
src/atlas/
  tools/             ingest, trimming, enrichment, registry, rag, system, find_tools
  retrieval/         embedders, Qdrant tool index
  agent/             middleware, builder, turn runner, run log, prompt
  backend/           Backend interface, mock PayPal, seed data
  evals/             cases, scorers, R0 runner, agent runner, report
evals/               cases.jsonl, baselines, fixtures, results
reports/             ingest sizes, R0 tuning notes
```

See [plan.md](plan.md) and [architecture.md](architecture.md) for the full plan and design contracts, and [docs/decisions.md](docs/decisions.md) for every decision made along the way and every problem hit, with its cause, fix and check.

## License

MIT. PayPal's OpenAPI specs under `specs/paypal/` keep their own Apache-2.0 license.
