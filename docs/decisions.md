# Decisions and problems

How Atlas got to its current shape: the design decisions made along the way, and the problems hit while building it, with what caused each one, how it was fixed and how the fix was checked. Numbers come from the repo's own runs on 2026-10-24.

## Decisions

### Approach and stack

| Decision | Options weighed | Chosen | Why |
|---|---|---|---|
| How to handle 100+ tools | Tool retrieval; supervisor + domain sub-agents; "tool search" meta-tools; code over a generated SDK; trained router | **Single agent with tool retrieval** (top-k tools per model call) | Scales by adding vectors rather than redesigning. One model hop per step instead of a supervisor hop plus a sub-agent hop. A routing miss can be recovered in the same run (`find_tools`), while a wrong sub-agent handoff can't. Multi-agent is kept for a phase-2 comparison on the same eval cases. |
| Model (final) | Ollama cloud `deepseek-v4.1-flash`; local `deepseek-r1:8b` / `14b` | **Local `deepseek-r1:8b` via Ollama** (16k-context variant) | Groq kept failing on its own schema checks, so Ajay switched to Ollama and DeepSeek. The cloud model was checked first, but it's priced per token, against the "free of cost" rule. The 8b local model is DeepSeek-R1-0528 distilled onto Qwen3 8B, tagged for tools: 5.2 GB, fits the 24 GB M2 with room to spare, no rate limits. |
| Model (before) | Groq free tier: `openai/gpt-oss-120b`, `openai/gpt-oss-20b`, `qwen/qwen3.8-27b` | **`openai/gpt-oss-120b`, reasoning effort low** | Gemini's free tier allowed 20 requests a day (problem 29). Ajay moved to Groq. gpt-oss-120b is the strongest tool-calling model Groq offers; low reasoning effort keeps reasoning tokens inside the 8k-per-minute cap. |
| Model (earlier) | DeepSeek via OpenRouter (first choice); then free tiers: Gemini, Mistral, Groq, OpenRouter `:free`, GitHub Models, local Ollama | **`gemini-3.5-flash` on the Gemini API free tier** (was `deepseek/deepseek-v4-flash` via OpenRouter) | The OpenRouter account had never bought credits, so calls were refused (problem 21), and the model had to be free. Groq's free plan allows 8k tokens a minute (about one Atlas call), OpenRouter `:free` 50 requests a day and GitHub Models about 150. Gemini's free tier allows 250k input tokens a minute, with tool calling and 1M context. 3.5-flash was picked over 3.5-flash-lite and 3-flash-preview after all three passed a tool-call probe. The client is provider-agnostic, so switching back is a settings change. |
| Agent framework | Plain Python loop; LangGraph; LangChain `create_agent`; CrewAI | **LangChain 1.4.7 `create_agent` with custom middleware** | Its `wrap_model_call` hook can swap the tool list on every model call, which is exactly what retrieval needs. The approval pause, retries and call limits come built in. |
| Tracing | Local logs only; LangSmith | **LangSmith**, project `atlas` | Every model and tool call is traced, and each agent-eval case records its trace link. |
| Embeddings | bge-small (local); OpenAI; Voyage | **`BAAI/bge-small-en-v1.5`, local** | DeepSeek has no embeddings API. Local means free, offline and no second vendor. bge-base was tested and wasn't measurably better (see tuning). |
| Vector store | FAISS; Chroma; Qdrant (embedded or server) | **Qdrant v1.19.2 server in Docker** | FAISS crashed on macOS (problem 7). Qdrant's grouped search returns one result per tool from several vectors per tool, with no post-processing, and filters become payload filters. v1.20.0 was 3 days old, so the server is pinned to v1.19.2. |
| Tool source | Postman collection; OpenAPI specs; hand-written tools | **PayPal's public OpenAPI specs** (commit `90e8041`, Apache-2.0) | 115 operations with real input schemas. With `rag_search` and `system_search` that's 117 tools, over the 101 minimum. The same parser loads other services in phase 2. |
| What answers tool calls | PayPal sandbox; mock; both | **In-process mock** | Eval results come out the same every run, and no sandbox account is needed. Behaviour lives in `seed.json`, so the code stays generic. |

### Tool definitions

| Decision | Chosen | Why / evidence |
|---|---|---|
| How much schema to show | Resolve `$ref` to depth 3; drop read-only fields, examples, `x-*` keys and **all** header parameters; cut descriptions to 120 characters; at most 20 enum values | Raw schemas total about 369k tokens, about 3× the original 128k context. After trimming they total about 57k. |
| Tools still too big | Trim again at depth 2 (descriptions 120, then 60 characters). **Never go below depth 2.** | Depth 1 stripped `items` and `primary_recipients` from `invoices_create`, so the call became useless. 11 tools stay over 1.5k tokens and are listed with that reason in `reports/ingest_sizes.md`. |
| Required fields | Always kept, at any depth | The resolver keeps following required properties past the depth limit, and a test compares the required paths of every trimmed schema with the full one. |
| Read vs write | `GET` is read. POSTs that only search or compute (invoice search, next invoice number, QR code, eligible payment methods, webhook signature check) are read via `specs/paypal/overrides.json`. Everything else is write. | Write tools pause for approval and count as "unexpected changes" in evals. Tagging a search as a write blocked harmless calls. |
| Example requests per tool | 5: 3 direct requests and 2 questions that need the tool's data | Users ask "what did I sell last month?" and never say `search_get`. Indirect questions close that gap. |

### Web UI

| Decision | Options weighed | Chosen | Why |
|---|---|---|---|
| Stack | Vite + React + TS with Penny's CSS; the same with Tailwind; React from a CDN | **Vite + React 19 + TypeScript, Penny's CSS ported** | Keeps Penny's look exactly, with no CSS framework, and the same base as agents-mvp. |
| Screens | Chat timeline; approvals; retrieval inspector; recent runs and examples | **Chat timeline, approvals, retrieval inspector** | Ajay's pick. The inspector shows the project's core idea: which tools out of 115 the model saw on each call. |
| Serving | FastAPI serves the build; a separate dev server only | **FastAPI serves `web/dist`** (Vite proxies `/api` in development) | One command, no CORS, the same pattern as Penny. |
| Streaming | NDJSON; Server-Sent Events; WebSockets | **NDJSON over a POST** | Same as Penny: one JSON event per line, simple to parse, works with `fetch` and an `AbortController`. |

### Evaluation

| Decision | Chosen | Why |
|---|---|---|
| Case set | 151 hand-written cases: 81 single-tool, 30 multi-step, 15 RAG, 10 system, 15 "should ask a question" | Covers every tool group plus the brief's three sample requests. |
| Tuning vs reporting | **60 dev cases for tuning, 91 test cases held out** | Tuning on the cases you report inflates the scores. Every tuning decision below used dev only. |
| Leakage guard | Fail any case with cosine similarity > 0.9 to a stored example request | 11 cases tripped it on the first run and were rewritten by hand. |
| Retrieval metrics | Recall@k, Precision@k, MRR, nDCG@k at k = 3, 5, 8, 10 | As specified. Precision@5 is capped at 0.2 on single-tool cases, so it's used to compare k values, not as a target. |
| Agent metrics | Tool execution success, task completion, p95 latency, cost per task, from one plain run (`atlas eval agent`) | As specified. Task completion also shows whether `find_tools` recovered first-search misses. |
| Eval scope | Started as a 9-config matrix (all-tools baseline, k sweep, description-only, no `find_tools`, LangChain's LLM selector) run as LangSmith experiments with an HTML report. **Cut back** to R0 retrieval metrics plus one agent run. | Ajay's call: the matrix was overkill for this use case. The dev/test split, the leakage check and the CI baseline stay, because they're free and keep the numbers honest. |
| Approval in evals | Off; a scorer fails any successful write the case didn't expect | The pause needs a person. The CLI keeps it on. |
| Fixed date | Evals run with today = 2026-10-24 | "Last month" always means September 2026, matching the seeded transactions. |
| Harness errors | An exception in a turn is status `error`, left out of the scores and reported separately; the run exits non-zero | Without this, an API outage looked like a weak agent (problem 21). |

### Retrieval tuning (dev split only)

Full table in [reports/r0_tuning.md](../reports/r0_tuning.md).

| Variant | Recall@8 | MRR | Kept? |
|---|---:|---:|---|
| bge-small, 5 examples, dense | **0.948** | 0.720 | **Yes** |
| bge-small, hybrid dense + BM25 (RRF) | 0.833 | 0.662 | No: worse on every setup |
| bge-base, 5 examples, dense | 0.938 | 0.777 | No: within noise, 3× larger |
| 10 examples per tool (either model) | 0.927 | ~0.78 | No: within noise |

- **Targets revised after R0, as planned.** The first guesses (Recall@5 ≥ 0.95, MRR ≥ 0.85) aren't reachable by one search, because most misses are multi-step requests that need two tools from one query. Inside the agent, `find_tools` covers those, and task completion shows whether it worked.
- **Held-out test R0:** Recall@8 0.921, Recall@5 0.857, MRR 0.743, nDCG@5 0.745. That's 0.009 under the 0.93 Recall@8 target, and left there rather than tuned on test data. The CI baseline is 0.9206.

### Agent design

| Decision | Chosen | Why |
|---|---|---|
| Where retrieval runs | `abefore_model` searches and stores `allowed_tools` in state; `awrap_model_call` filters the request's tools | All 118 tools are registered once, so any of them can run, but the model sees only about 11 per call. |
| Multi-step fallback | `find_tools(query)` writes its matches into agent state, and the middleware adds them on the next call | Covers "create, then send": in the first live run the model found `invoices_send` this way. |
| Search text | The last 2 user messages | Follow-ups ("and the one from last week?") keep their context. |
| Knowledge base | A handbook written for a fictional merchant (Northwind Studio) | Avoids copying PayPal's docs, and gives RAG answers exact facts to check. |
| Repo | Private repo on the personal GitHub (`ajay-drew`), commits as Ajay A with a personal email, set for this repo only | The global git identity is the work one. The repo goes public once results are in. |

## Problems and fixes

| # | Problem | Cause | Fix | Checked by |
|---|---|---|---|---|
| 1 | No DeepSeek key on the machine; the only LangSmith keys were the employer's | — | Waited for personal keys rather than borrowing work ones. Keys live only in the gitignored `.env`. | Smoke test with personal keys |
| 2 | Smoke test crashed with LangSmith 401 | An empty `LANGSMITH_API_KEY=` line counted as a key, so tracing turned on with a blank token | Blank keys count as unset | `test_blank_keys_count_as_unset`; smoke passes |
| 3 | All tool definitions ≈ 400k tokens, about 3× the 128k context | Raw OpenAPI schemas are huge (orders alone ≈ 47k) | The trimming rules above | `reports/ingest_sizes.md`: 369k → 57k |
| 4 | Depth-limited trimming could cut off required nested fields | `$ref` resolution stopped at depth 3 regardless | Past the limit, the resolver follows required properties only | `test_trimming_never_drops_a_required_field` |
| 5 | Staged trimming emptied useful tools | Depth 1 removed `items` and `primary_recipients` | Depth-2 floor; leftovers listed with a reason | Size report plus a manual schema check |
| 6 | PayPal operation IDs (`plans.create`) aren't valid tool names | The model API needs `^[a-zA-Z0-9_-]{1,64}$` | Safe names plus `original_id` kept on each tool | `test_safe_name_maps_dots_and_prefixes` |
| 7 | Index build segfaulted (exit 139) | FAISS imported before torch on macOS: two OpenMP runtimes | Root cause found (import order). Moved to a Qdrant server, as Ajay decided. | Index builds; 690 vectors stored |
| 8 | Newest Qdrant was too new to pin | v1.20.0 was 3 days old | Pinned server v1.19.2 and client 1.19.1 | `docker-compose.yml`, `uv.lock` |
| 9 | Retrieval ranked the wrong tools for the brief's requests | HTML (`<ul>`, `<blockquote>`) in descriptions; examples had no indirect questions | Strip HTML at ingest; example mix of 3 direct + 2 indirect | Re-run R0 on dev |
| 10 | 11 eval cases nearly copied stored example requests | Similar phrasing, cosine > 0.9 | Rewrote them by hand, keeping intent and IDs | `atlas eval leakage` → 0 |
| 11 | Hybrid search looked promising but lost 0.05–0.11 Recall@8 | BM25 on short example sentences full of IDs and amounts is noisy, and fusion pulls in lookalikes | Kept dense only; hybrid stays as an off-by-default setting | `reports/r0_tuning.md` |
| 12 | Test-split Recall@8 (0.921) missed the 0.93 target | Multi-step requests | Not tuned on test; `find_tools` covers multi-step gaps inside the agent | CI baseline 0.9206 |
| 13 | 13 tools failed a minimal valid call | Invented seed IDs broke spec patterns (order IDs are `^[A-Z0-9]+$`); the input generator ignored `pattern` and `required` next to `allOf` | Real-format seed IDs (eval cases updated to match); pattern-aware generator that merges `allOf` | `test_every_tool_succeeds_with_a_valid_minimal_input`: 115/115 |
| 14 | The model passed nested inputs as JSON strings (`"path": "{\"invoice_id\": ...}"`) | DeepSeek quirk | Tool wrapper parses JSON strings before checking; run records store the parsed version | `test_nested_json_strings_are_parsed`; inv-s03 scored correctly |
| 15 | The agent wandered on "send an invoice" and hit the 8-call limit | It looked up templates and the merchant's business info nobody asked for | Prompt rule: fill in what the request gives and what's required; don't look up optional details | Two live runs: one clean, one still wandered. Measured in evals, not tuned further on anecdotes. |
| 16 | Turn status was wrong both ways | "Ends with ?" missed questions mid-answer, and caught follow-up offers | `asked_user` = the answer contains a question and nothing changed; clarify cases scored on "no change attempted + a question" | `test_middleware.py` status tests |
| 17 | The approval-pause test never paused | The model asked for the cancellation reason the API requires | Re-ran with a reason. The call paused, the rejection was respected, and the subscription stayed ACTIVE. | Manual run, recorded |
| 18 | Eval upload got LangSmith 401 | `langsmith.Client()` reads environment variables, but keys live in settings | One `langsmith_client(settings)` factory used everywhere | Experiment `atlas-r2-…` created |
| 19 | OpenRouter 402: "requested up to 131072 tokens" | No `max_tokens`, so each call reserved the model's full output against the key limit | `max_tokens=4096` (`ATLAS_MAX_OUTPUT_TOKENS`) | Enrichment and agent calls succeed |
| 20 | Re-running enrich nearly regenerated all 115 tools' examples | The prompt text is part of the cache key, and an edit made it configurable | Restored the committed examples and re-keyed the cache to the current prompt | `atlas enrich` → 0 regenerated; R0 baseline still 0.9206 |
| 21 | Full eval runs reported 0% completion | OpenRouter: "Insufficient credits. This account never purchased credits." After about $0.20 of usage, every call was refused, and the harness counted those as agent failures | Stopped the runs and deleted the invalid result files. Exceptions are now status `error`, left out of scores, and fail the command. | 40 tests; **eval re-run waits on credits** |
| 22 | Qdrant 408 timeouts with 8 cases in flight | Client default timeout too short under concurrent searches | Client timeout raised to 30 s | Re-run pending (blocked by 21) |
| 23 | Mock crashed on a PATCH into a list (`'list' object has no attribute 'setdefault'`) | JSON-patch paths like `/billing_cycles/0/...` | The patch walker handles list indexes | `test_patch_into_a_list_does_not_crash` |
| 24 | Gemini rejected every request with Atlas's tools: `schema at properties.body requires unspecified property 'operations'` | PayPal schemas list `required` at one level while defining the property inside an `allOf` branch. Standard JSON Schema allows it; Gemini doesn't. | Ingest merges `allOf` branches into one object and keeps `required` to properties defined at the same level. Trimmed schemas shrank from ~57k to ~50.6k tokens. | One Gemini request with all 115 tools succeeded; required-field test still passes |
| 25 | Changing trimming would have regenerated every example again | The enrichment cache key included the trimmed schema | The cache key now covers only the prompt and the operation's name, summary and description; the existing examples were re-keyed | `git diff` shows only the 115 hash lines changed; R0 unchanged |
| 26 | `gemini-2.5-flash` returned 404 "no longer available to new users" | Retired for new API keys | Probed the current Flash models with one tool call each and picked from those | Probe results recorded above |
| 27 | Gemini 429: "input tokens per minute limit exceeded on Free Tier" (limit 250,000, retry after ~50 s) | One all-tools request is ~65k tokens; a few in a row pass the per-minute cap | `ModelRetryMiddleware` (15 s initial, doubling to 60 s, 5 retries), and the agent eval runs 2 cases at a time | Agent eval run |

| 28 | Every agent turn failed on its second model call: "Function call is missing a thought_signature" | Gemini 3 is a thinking model; each tool call carries a signature that must be sent back. LangChain's OpenAI client drops Google's extra fields. | Native `ChatGoogleGenerativeAI` (`langchain-google-genai` 4.4.1) behind a provider registry (`ATLAS_LLM_PROVIDER`); the OpenAI-compatible path stays for other providers | A multi-step turn on Gemini completed with recovery from a bad input |
| 29 | A test turn hung for 10+ minutes | `gemini-3.5-flash`'s free tier allows **20 requests per day per model**, and the retry middleware kept waiting on a daily limit as if it were per-minute | Retry only per-minute limits and server errors; a daily-quota 429 fails the turn at once | `test_daily_quota_is_not_retried_but_per_minute_is` |

| 30 | Every Groq model returned 413 "Request too large": limit 8,000, requested ~10,700 | Groq's free tier caps each request (and each minute) at 8,000 tokens; 9 retrieved tools plus the prompt was ~10.7k | A request token budget in `ToolRetrievalMiddleware`: tools join in priority order until the request would exceed `ATLAS_MAX_REQUEST_TOKENS` (7,000) | Middleware budget test; Groq turns no longer 413 |
| 31 | A "no descriptions" trim level came out larger than the 60-character one | `_cut(text, 0)` sliced `text[:-1]`, keeping almost the whole description | Not used: the budget made a tighter trim level unnecessary. The largest tool after the `allOf` merge is ~3.3k tokens, under the cap. | Size measurements |

| 32 | One Groq eval case failed before Atlas saw the tool call: "parameters for tool disputes_list did not match schema: 'user_123' does not match pattern" | Groq validates tool arguments against the schema on its own server and returns 400, so the harness can't hand the error back to the model | Recorded as a known limitation of running on Groq; the case is left out of the scores as a harness error | Groq eval log |

| 33 | The UI turn failed: Groq rejected `invoices_list` because `fields: "amount,status,detail"` broke the pattern `(?i)^(all\|none)$` | Same as 32: Groq validates tool arguments server-side and fails the whole request | `ToolCallRepairMiddleware` catches `tool_use_failed`, hands the reason to the model and retries up to twice. Then Ajay moved off Groq anyway. | `tests/test_repair.py` |
| 34 | Ollama's default context window is small, and longer prompts are cut silently | Ollama defaults, not an error | `ollama/Modelfile` builds a 16k-context variant, and the request budget is set to 12k | Ollama run |

## Open items

- Problem 21 is resolved by moving to the Gemini free tier, but problem 29 limits it: 20 requests a day on `gemini-3.5-flash` is far below the ~320 calls a 91-case agent eval needs. Other Flash models have separate daily quotas, visible only in AI Studio.
- Both API keys were pasted into a chat; rotate them when the project wraps up.
