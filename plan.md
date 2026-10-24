# Atlas build plan

This file is the source of truth for what gets built and in what order. Work follows it step by step. A decision changes here first, in its own edit, before any code depends on it. Tick a box only when its check has actually passed.

## Goal

Atlas is a chat agent that can use 100+ API tools without its accuracy falling apart. On every model call it searches the tool list and gives the model only the tools that match the request. An eval harness proves this with numbers.

Phase 1 uses PayPal's 115 REST operations, plus `rag_search` and `system_search`: 117 tools in total. Phase 2 grows the tool list to 2,000 to show how it scales.

## Scope

**In:** tool ingest from OpenAPI, tool retrieval, the LangChain agent, a mock PayPal backend, RAG, system search, LangSmith tracing, the eval harness, CI, and a public GitHub repo.

**Out (for now):** real PayPal sandbox calls, a web UI, multi-agent routing (phase 2 comparison only), fine-tuned routers, and auth/multi-user.

## Decisions

| Area | Decision |
|---|---|
| Name | Atlas. The repo is `tool-retrieval-agent` and the package is `atlas`. |
| Approach | Single agent with tool retrieval: the top 8 tools per model call, plus 3 tools that are always available |
| Framework | LangChain 1.4.7 `create_agent` with custom middleware |
| Model | DeepSeek `deepseek/deepseek-v4-flash` through OpenRouter, temperature 0, using `ChatOpenAI` from `langchain-openai` with OpenRouter's base URL. A fixed version, never a `~latest` alias, so eval runs stay comparable. Context is 1M tokens. |
| Embeddings | `BAAI/bge-small-en-v1.5`, run locally through sentence-transformers |
| Vector index | Plain `faiss-cpu` 1.15.1 `IndexFlatIP` (exact search, no LangChain wrapper) |
| Tool source | PayPal OpenAPI specs, commit `90e8041`, copied into `specs/paypal/` with their Apache-2.0 LICENSE |
| Backend | A mock PayPal run in the same process, behind a backend interface |
| Fallback | A `find_tools(query)` tool whose results are saved to agent state |
| Approval pause | `HumanInTheLoopMiddleware` on write tools in the CLI. Off in evals, where a scorer checks write calls instead. |
| Tracing | LangSmith, project `atlas`, turned on by env vars |
| Evals | LangSmith dataset plus `aevaluate`; local JSON results and an HTML report as well |
| Python | 3.12, managed with `uv` |
| License | MIT for our code |

## Engineering rules

- Async all the way through: `ainvoke`, async tools, and async clients. No blocking client wrapped in a thread.
- SOLID. New services, scorers and backends are added as new classes or registry entries, never as another `if` branch in shared code.
- Interfaces at every input/output boundary: `ToolIndex`, `Backend`, `Embedder`. The agent depends on these interfaces, not on FAISS or the mock directly.
- No inline comments. A one-line docstring only where the name and signature don't explain something.
- Pinned dependencies in `uv.lock`.
- Secrets live only in `.env`, which is gitignored. Only `.env.example` is committed.
- No internal names, code or data from any employer.
- Tests cover ingest, middleware and scorers. Run only the test files that relate to a change, never the whole suite.

## Phase 1: PayPal, 117 tools

### 1. Project setup
- [x] `uv init`, package `atlas` under `src/`, Python 3.12
- [x] Dependencies pinned: langchain, langchain-openai, langsmith, faiss-cpu, sentence-transformers, jsonschema, pydantic-settings, typer, ruff, pytest
- [x] `.env.example`, `.gitignore`, MIT `LICENSE`, README stub
- [x] `config.py` reads every setting from env (see architecture.md, Config)
- [x] Smoke test: the OpenRouter model makes one tool call, and the trace shows up in LangSmith

**Done when** `uv run atlas smoke` prints a tool call and a LangSmith trace link.

### 2. Ingest and trim
- [x] `specs/paypal/` holds the 13 files and LICENSE, pinned to commit `90e8041`
- [x] `atlas ingest` writes `data/tools.json` with 115 `ToolSpec` records
- [x] Names are made safe (`plans.create` becomes `plans_create`) and map back to the original ID
- [x] Every trimming rule from architecture.md is applied, and required fields are never dropped
- [x] A size report lists each tool's tokens before and after trimming
- [x] Unit tests cover reference resolution, trimming and naming

**Done when** there are 115 tools, every trimmed schema is valid JSON Schema, and no tool is over 1.5k tokens. Any tool over the limit is listed with a reason.

### 3. Enrich and index
- [ ] `atlas enrich` adds a one-line purpose and 5 example requests per tool, cached in `data/enrichment.json`
- [ ] `atlas index` builds the FAISS index: up to 6 vectors per tool, and a tool's score is its best vector
- [ ] `atlas search "<text>" --k 8` prints the ranked tools with their scores

**Done when** `atlas search "send an invoice for $50"` puts an invoice tool in the top 3.

### 4. First eval: retrieval only (R0)
- [ ] `evals/cases.jsonl` starts with 60 hand-written cases (schema in architecture.md)
- [ ] A leakage check flags any case with cosine similarity > 0.9 to a stored example request
- [ ] Recall@k, Precision@k, MRR and nDCG@k at k = 3, 5, 8 and 10, broken down by spec file
- [ ] `atlas eval retrieval` writes `evals/results/<timestamp>-r0.json`
- [ ] CI runs ruff and R0 on every push, and fails if Recall@8 drops below the last committed result
- [ ] Tune the index with R0 before building the agent

**Done when** R0 runs in under 30 seconds with no API key and Recall@8 ≥ 0.95 on the 60 cases.

### 5. Mock backend and tool registry
- [ ] A `Backend` interface, with `MockPayPal` as its first implementation
- [ ] The mock checks inputs against the full schema, keeps seeded data (invoices, transactions, disputes, orders, subscriptions, products), and resets for each case
- [ ] Every other operation returns a placeholder in the right shape
- [ ] The registry builds one async `StructuredTool` per `ToolSpec`

**Done when** every one of the 115 tools can be called with a valid example input and returns success.

### 6. Agent
- [ ] `ToolRetrievalMiddleware` (`wrap_model_call`, using `request.override(tools=…)`)
- [ ] `build_atlas(config)` uses `create_agent` with our middleware, approval pause, retry and limits, and an `InMemorySaver` checkpointer
- [ ] A run log row is written for every finished turn
- [ ] `atlas chat`, an interactive CLI that asks for approval on write tools
- [ ] Unit tests check that the middleware passes exactly top-k + always-on + found tools

**Done when** the three sample requests from the brief work in `atlas chat` and each has a LangSmith trace.

### 7. Extra tools
- [ ] `rag_search` over `kb/`, with its own FAISS index and source names in results
- [ ] `system_search` with `scope=tools` (the tool index) and `scope=runs` (the run log)
- [ ] `find_tools` returns matches and saves them to state

**Done when** "what tools manage invoices?", "status of my last request" and one knowledge-base question each get a correct answer.

### 8. Full evals and report
- [ ] 150 cases: 80 single-tool, 30 multi-step, 15 RAG, 10 system, 15 that should get a question back
- [ ] Cases are synced to the LangSmith dataset `atlas-paypal-v1`
- [ ] R1: baseline with all tools in the prompt, both trimmed (about 50k tokens) and untrimmed (about 400k, which fits in v4-flash's 1M context)
- [ ] R2: Atlas with k = 8
- [ ] R3: k sweep; description-only vs. with examples; `find_tools` on vs. off; LangChain's `LLMToolSelectorMiddleware` vs. FAISS
- [ ] `atlas eval report` writes `evals/report.html` and the README results table

**Done when** the README shows R0–R3 next to the targets below.

## Phase 1 targets

| Metric | Target |
|---|---|
| Recall@5 | ≥ 0.95 |
| Precision@5 | Compare across k (at most 0.2 on single-tool cases) |
| MRR | ≥ 0.85 |
| nDCG@5 | ≥ 0.85 |
| Tool execution success | ≥ 0.95 |
| Task completion rate | ≥ 0.85 |
| p95 latency, cost per task | Lower than the R1 baseline |

These are first guesses. Change them here, with a reason, after R0.

## Phase 2: scale to 2,000 tools

- [ ] Add more public OpenAPI specs through the same ingest. Stripe and Square go first because they are the hardest lookalikes.
- [ ] Prefix tool names with their service (`stripe__invoices_create`) and filter by service when the user names one
- [ ] R4: scaling curve at 117, 500, 1,000 and 2,000 tools
- [ ] Optional: a multi-agent version on the same cases for comparison
- [ ] If recall drops, decide between a reranker, bge-base or a service filter, based on the R4 numbers

## Open questions

- Is a CLI enough for the demo, or should there be a web chat page?
- What's the submission deadline? It decides whether phase 2 makes the cut.

## Change log

- 2026-10-24: plan created.
- 2026-10-24: model provider changed to OpenRouter (`deepseek/deepseek-v4-flash`, $0.091 / $0.182 per 1M tokens in / out). `langchain-deepseek` replaced by `langchain-openai`. The 1M context means R1 can also run untrimmed.
- 2026-10-24: step 2 done. 115 tools, ~369k → ~57k tokens. Over-budget tools are trimmed down to a depth-2 floor; 11 stay over 1.5k and are listed in reports/ingest_sizes.md. All header parameters are dropped.
- 2026-10-24: step 1 built. LangSmith tracing is scoped with `tracing_context` and its own `Client`, rather than by changing environment variables. The smoke test waits on keys.
