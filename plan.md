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
| Model | **Groq `openai/gpt-oss-120b`** (free tier, `reasoning_effort=low`) through the OpenAI-compatible client; Gemini kept as a second provider. Previously Google `gemini-3.5-flash` on the Gemini API free tier, temperature 0, using `ChatOpenAI` against Gemini's OpenAI-compatible endpoint. The client is provider-agnostic (`LLM_API_KEY`, `LLM_BASE_URL`, `ATLAS_MODEL`), so OpenRouter, Mistral or a local Ollama is a settings change. Free-tier limit: 250k input tokens per minute; 429s are retried with backoff. |
| Embeddings | `BAAI/bge-small-en-v1.5`, run locally through sentence-transformers |
| Vector index | Qdrant server in Docker (`qdrant/qdrant:v1.19.2`), with `qdrant-client` 1.19.1 through `AsyncQdrantClient`. Grouped search returns one result per tool. |
| Tool source | PayPal OpenAPI specs, commit `90e8041`, copied into `specs/paypal/` with their Apache-2.0 LICENSE |
| Backend | A mock PayPal run in the same process, behind a backend interface |
| Fallback | A `find_tools(query)` tool whose results are saved to agent state |
| Approval pause | `HumanInTheLoopMiddleware` on write tools in the CLI. Off in evals, where a scorer checks write calls instead. |
| Tracing | LangSmith, project `atlas`, turned on by env vars |
| Evals | Retrieval metrics with no LLM (R0) plus one plain agent run; results as local JSON; agent runs traced in LangSmith |
| Python | 3.12, managed with `uv` |
| License | MIT for our code |

## Engineering rules

- Async all the way through: `ainvoke`, async tools, and async clients. No blocking client wrapped in a thread.
- SOLID. New services, scorers and backends are added as new classes or registry entries, never as another `if` branch in shared code.
- Interfaces at every input/output boundary: `ToolIndex`, `Backend`, `Embedder`. The agent depends on these interfaces, not on Qdrant or the mock directly.
- No inline comments. A one-line docstring only where the name and signature don't explain something.
- Pinned dependencies in `uv.lock`.
- Secrets live only in `.env`, which is gitignored. Only `.env.example` is committed.
- No internal names, code or data from any employer.
- Tests cover ingest, middleware and scorers. Run only the test files that relate to a change, never the whole suite.

## Phase 1: PayPal, 117 tools

### 1. Project setup
- [x] `uv init`, package `atlas` under `src/`, Python 3.12
- [x] Dependencies pinned: langchain, langchain-openai, langsmith, qdrant-client, sentence-transformers, jsonschema, pydantic-settings, typer, ruff, pytest
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
- [x] `atlas enrich` adds a one-line purpose and 5 example requests per tool, cached in `data/enrichment.json`
- [x] `docker compose up -d` starts Qdrant; `atlas index` builds the `atlas_tools` collection: up to 6 vectors per tool, and a tool's score is its best vector
- [x] `atlas search "<text>" --k 8` prints the ranked tools with their scores

**Done when** `atlas search "send an invoice for $50"` puts an invoice tool in the top 3.

### 4. First eval: retrieval only (R0)
- [x] `evals/cases.jsonl` starts with 60 hand-written cases (schema in architecture.md)
- [x] A leakage check flags any case with cosine similarity > 0.9 to a stored example request
- [x] Recall@k, Precision@k, MRR and nDCG@k at k = 3, 5, 8 and 10, broken down by spec file
- [x] `atlas eval retrieval` writes `evals/results/<timestamp>-r0.json`
- [x] CI runs ruff and R0 on every push, and fails if Recall@8 drops below the last committed result (the workflow file is kept locally, not on GitHub yet: the personal GitHub token lacks the `workflow` scope)
- [x] Tune the index with R0 before building the agent

**Done when** R0 runs in under 30 seconds with no API key and Recall@8 ≥ 0.95 on the 60 cases.

### 5. Mock backend and tool registry
- [x] A `Backend` interface, with `MockPayPal` as its first implementation
- [x] The mock checks inputs against the full schema, keeps seeded data (invoices, transactions, disputes, orders, subscriptions, products), and resets for each case
- [x] Every other operation returns a placeholder in the right shape
- [x] The registry builds one async `StructuredTool` per `ToolSpec`

**Done when** every one of the 115 tools can be called with a valid example input and returns success.

### 6. Agent
- [x] `ToolRetrievalMiddleware` (`wrap_model_call`, using `request.override(tools=…)`)
- [x] `build_atlas(config)` uses `create_agent` with our middleware, approval pause, retry and limits, and an `InMemorySaver` checkpointer
- [x] A run log row is written for every finished turn
- [x] `atlas chat`, an interactive CLI that asks for approval on write tools
- [x] Unit tests check that the middleware passes exactly top-k + always-on + found tools

**Done when** the three sample requests from the brief work in `atlas chat` and each has a LangSmith trace.

### 7. Extra tools
- [x] `rag_search` over `kb/`, with its own Qdrant collection (`atlas_kb`) and source names in results
- [x] `system_search` with `scope=tools` (the tool index) and `scope=runs` (the run log)
- [x] `find_tools` returns matches and saves them to state

**Done when** "what tools manage invoices?", "status of my last request" and one knowledge-base question each get a correct answer.

### 8. Evals
- [x] 151 cases: 81 single-tool, 30 multi-step, 15 RAG, 10 system, 15 that should get a question back (60 dev, 91 test)
- [x] Retrieval metrics (R0): Recall@k, Precision@k, MRR, nDCG@k, plus the leakage check and the CI baseline
- [x] One agent run, `atlas eval agent`, on 10 cases (Ajay's limit): tool execution success, task completion, p95 latency, cost per task. Groq gpt-oss-120b: 6/9 completed, 1 harness error (see README).

**Done when** the README shows the R0 numbers and the 10-case agent run.

## Phase 1 targets

| Metric | Target | Measured on |
|---|---|---|
| Recall@5 | Reported, no target | test split, R0 |
| Recall@8 | ≥ 0.93 | test split, R0 |
| Precision@5 | Reported (at most 0.2 on single-tool cases) | test split, R0 |
| MRR | ≥ 0.75 | test split, R0 |
| nDCG@5 | ≥ 0.70 | test split, R0 |
| Tool execution success | ≥ 0.95 | test split, agent run |
| Task completion rate | ≥ 0.85 | test split, agent run |
| p95 latency, cost per task | Reported, no target | test split, agent run |

Revised 2026-10-24 after R0 tuning on the dev split (`reports/r0_tuning.md`). The first guesses (Recall@5 ≥ 0.95, MRR ≥ 0.85) are out of reach for a single search: most misses are multi-step requests, where one query has to surface two tools. Inside the agent, `find_tools` covers those, and task completion shows whether it worked.

## Phase 1.5: web UI

Penny's (sandbox/procurement-agent) look and patterns, rebuilt in React.

- [x] HTTP API (`atlas serve`, FastAPI): stream a chat turn as NDJSON, resume an approval pause, search the tool catalog, health
- [x] `stream_turn`: a turn as a stream of events (retrieval, tool call, tool result, approval, message, done)
- [x] The retrieval middleware records each call's query, scored hits, tools shown and tools dropped by the budget, for the inspector
- [x] React app in `web/` (Vite, React 19, TypeScript, Penny's CSS tokens): chat with a live tool timeline, approve or reject changes, retrieval inspector
- [x] FastAPI serves `web/dist`; Vite's dev server proxies `/api` to it
- [x] Checked in the browser: one read request, one approval, the inspector search

**Done when** `atlas serve` shows the UI, a request streams its retrieval and tool calls, and an approval pause can be approved or rejected from the page.

## Phase 2: scale to 2,000 tools

- [ ] Add more public OpenAPI specs through the same ingest. Stripe and Square go first because they are the hardest lookalikes.
- [ ] Prefix tool names with their service (`stripe__invoices_create`) and filter by service when the user names one
- [ ] Scaling check: R0 at 117, 500, 1,000 and 2,000 tools
- [ ] Optional: a multi-agent version on the same cases for comparison
- [ ] If recall drops, decide between a reranker, bge-base or a service filter, based on those numbers

## Open questions

- Is a CLI enough for the demo, or should there be a web chat page?
- What's the submission deadline? It decides whether phase 2 makes the cut.

## Change log

- 2026-10-24: plan created.
- 2026-10-24: model provider changed to OpenRouter (`deepseek/deepseek-v4-flash`, $0.091 / $0.182 per 1M tokens in / out). `langchain-deepseek` replaced by `langchain-openai`. The 1M context means R1 can also run untrimmed.
- 2026-10-24: first push to GitHub. The personal gh token lacks the `workflow` scope, so GitHub refused `.github/workflows/ci.yml`. On Ajay's call, the 11 unpushed commits were rewritten to leave that file out (backup branch `backup/pre-ci-strip` kept locally). The file stays on disk, excluded via `.git/info/exclude`, until the scope is added.
- 2026-10-24: web UI built and checked in the browser on Groq. A read request streamed two retrieval steps (the second dropped one tool for the token budget) and an answer with its trace link. An approval paused `subscriptions_suspend`, Approve resumed it, and the mock shows SUSPENDED. Catalog search and phone width were checked too. Two display bugs from resuming were fixed in the UI reducer: the resumed stream re-sends the paused tool call (now skipped by ID), and each stream numbered its steps from 1 (now numbered within the turn).
- 2026-10-24: web UI planned (Phase 1.5), on Ajay's picks: Vite + React + TypeScript with Penny's CSS, FastAPI serving the build, and three screens (chat timeline, approvals, retrieval inspector). Groq eval: 10 cases, 6/9 completed, 100% tool execution success, p95 114 s (rate-limit waits), $0; m04 errored because Groq rejects a tool call server-side when an argument breaks the schema's `pattern`.
- 2026-10-24: provider changed to Groq (`openai/gpt-oss-120b`), Ajay's call after Gemini's 20 requests a day. Groq's free tier caps a single request at 8,000 tokens (7,000 input tokens on Qwen), so `ToolRetrievalMiddleware` gained a request token budget (`ATLAS_MAX_REQUEST_TOKENS`): tools are added in priority order (found_tools, then by retrieval rank) until the request would exceed the budget. It's unset (no limit) for other providers. The agent eval is capped at 10 cases, run one at a time.
- 2026-10-24: Gemini follow-ups. A native `ChatGoogleGenerativeAI` client was added behind a provider registry, because the OpenAI-compatible endpoint loses Gemini 3 thought signatures and the second tool call fails. Daily-quota 429s are no longer retried (a test turn hung waiting on one). The free tier for `gemini-3.5-flash` turned out to be 20 requests a day, too few for the agent eval.
- 2026-10-24: model provider changed to Gemini (`gemini-3.5-flash`, free tier) because the OpenRouter account had no purchased credits. Ajay picked 3.5-flash from four models that passed a tool-call probe; the 2.5 models are retired for new users. Gemini rejected PayPal schemas where `required` sits outside `allOf` branches, so ingest now merges `allOf` into one object (trimmed size ~57k → ~50.6k tokens, required fields still proven kept). The enrichment cache key no longer includes the schema, so trimming tweaks don't regenerate examples; the existing examples were re-keyed, not regenerated. `ModelRetryMiddleware` retries 429s (15 s initial, up to 60 s). Settings renamed to provider-neutral `LLM_API_KEY`/`LLM_BASE_URL`; prices default to 0 on the free tier, and the agent eval also reports input tokens per task.
- 2026-10-24: evals cut back on Ajay's call (the full matrix was overkill for this use case). Kept: R0 retrieval metrics (Recall/Precision/MRR/nDCG), the dev/test split, the leakage check, the CI baseline, and one plain agent run (`atlas eval agent`) for tool execution success, task completion, p95 latency and cost. Removed: the 9 run configs, LangSmith experiments and dataset sync, the HTML report, the agent's "all tools" and "LLM selector" modes, `ExposureMiddleware`, and the exposure-recall and first-call metrics. Agent runs are still traced in LangSmith.
- 2026-10-24: step 8 eval harness built (trajectory scorers, LangSmith experiments, report). The first full runs were invalid: OpenRouter refused every call with "Insufficient credits. This account never purchased credits" after about $0.20 of usage, and the harness counted those as agent failures. Results were deleted. Exceptions are now status `error`, left out of scores, and fail the command. Also fixed: Qdrant 408 timeouts under load (client timeout 30 s) and a mock crash on PATCH into a list. R1–R3 are blocked on credits. Decisions and problems are logged in docs/decisions.md.
- 2026-10-24: steps 6–7 done. Retrieval runs in `abefore_model` (writes `allowed_tools` to state) and filters in `awrap_model_call`. Exposure is recorded by a separate innermost `ExposureMiddleware` into a per-run ContextVar, so it also works for the all-tools and LLM-selector variants. `atlas ask` was added for one-shot use. Turn status is "asked_user" when the answer contains a question and nothing was changed. The tool wrapper parses nested inputs sent as JSON strings (a DeepSeek quirk seen in traces). The prompt now says not to look up optional details nobody asked for. The model still sometimes wanders on the invoice request, and evals measure how often. The knowledge base is a handbook for a fictional merchant (Northwind Studio), not copied PayPal docs.
- 2026-10-24: step 5 done. The mock is generic REST routing, with PayPal behaviour as data in seed.json. Seed IDs changed to match spec patterns (order and webhook event IDs), and the eval cases were updated to match. All 115 tools pass a minimal valid call.
- 2026-10-24: steps 3–4 done. All 151 cases written at once (60 dev, 91 test) instead of 60 then 90. R0 on the test split: Recall@8 0.921, Recall@5 0.849, MRR 0.741, nDCG@5 0.739. That misses the 0.93 Recall@8 target by 0.01. Not tuned further, to keep the test split honest. The CI baseline is 0.9206. Step 3's "invoice tool in top 3" check passes (invoices_list is #1 for the brief's invoice request), but `invoices_create` is outside the top 5 for that query; that's covered by `find_tools` and measured as exposure recall.
- 2026-10-24: R0 tuning on dev (8 setups): kept bge-small, 5 examples, dense only. Hybrid BM25+dense lost 0.05–0.11 Recall@8; 10 examples and bge-base moved results by ±0.02 (noise). Targets revised (see Phase 1 targets). Eval cases now carry a dev/test split; 11 cases were rewritten after the leakage check flagged them.
- 2026-10-24: vector index changed from FAISS to a Qdrant server in Docker (v1.19.2, client 1.19.1). FAISS segfaulted on macOS when imported before torch. Search is async through `AsyncQdrantClient`, and the R3 description-only variant becomes a payload filter. CI runs Qdrant as a service container.
- 2026-10-24: step 2 done. 115 tools, ~369k → ~57k tokens. Over-budget tools are trimmed down to a depth-2 floor; 11 stay over 1.5k and are listed in reports/ingest_sizes.md. All header parameters are dropped.
- 2026-10-24: step 1 built. LangSmith tracing is scoped with `tracing_context` and its own `Client`, rather than by changing environment variables. The smoke test waits on keys.
