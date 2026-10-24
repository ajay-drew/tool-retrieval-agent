# Atlas design

How Atlas answers the brief: an agent that can act through 100+ tools (and in principle thousands) from a plain chat, without accuracy collapsing as tools are added. Each section follows one of the brief's pointers. Numbers come from this repo's own runs; [decisions.md](decisions.md) has every decision and problem in detail.

**The short answer:** never show the model the whole catalog. Atlas registers every tool but, before each model call, searches the catalog and passes only the tools that match: the top 8 plus 3 always-on tools. Each model call costs and behaves the same whether the catalog holds 115 tools or 2,000.

## 1. Agent structure

One agent, built with LangChain `create_agent` (a LangGraph state machine underneath). Each turn loops: retrieve tools → call the model → run any tool calls → repeat until the model answers.

What happens around each model call is handled by middleware, in this order:

| Middleware | Job |
|---|---|
| `ToolRetrievalMiddleware` | Picks the tools for this call (section 2) |
| `ToolCallRepairMiddleware` | If the provider rejects the model's tool call, hands the reason back so the model can fix it |
| `InjectionGuardMiddleware` | Marks tool results that try to instruct the model (section 7) |
| `HumanInTheLoopMiddleware` | Pauses every write tool for your approval |
| `ModelRetryMiddleware`, `ToolRetryMiddleware` | Retry rate limits and server errors |
| Call limits | At most 8 model calls and 12 tool calls per turn |

**Why one agent, not several:**
- **Routing cost:** a supervisor routing to specialist sub-agents (invoices, disputes, reports…) adds a model call to every request.
- **No recovery:** a wrong handoff can't be undone in the same turn.
- **Manual upkeep:** someone has to draw the domain lines by hand, and redraw them for every new API.

Retrieval does the same narrowing with a vector search instead of a model call, and when it misses, the model can search again itself (`find_tools`). Multi-agent would earn its place for domains that need different rules or a different model, not to cope with the number of tools.

## 2. Tool selection and routing

**Building the catalog (once):**
1. **Ingest:** each OpenAPI operation becomes a tool. Schemas are trimmed: `$ref`s resolved to depth 3; headers, read-only fields and examples dropped; `allOf` branches merged; long tools trimmed harder, down to a depth-2 floor. Required fields are never dropped, which a test proves. PayPal's 115 operations went from about 369k tokens to about 51k.
2. **Enrich:** a model writes each tool a one-line purpose and 5 example requests: 3 direct, and 2 questions that need the tool's data. That bridges the gap between "what did I sell last month?" and an API named `search_get`.
3. **Curated keywords** (data, per service): for tools whose names hide what they're for. The transactions tool gets "sales, revenue, income…".
4. **Index:** each tool becomes about 6 vectors in Qdrant (description, examples, keywords). Grouped search returns ranked *tools*, each scored by its best vector.

**At run time, before every model call:**
- **Search:** the last two user messages are the query, and the top 8 tools plus `find_tools`, `rag_search` and `system_search` are passed to the model.
- **Fit the request budget:** for providers that cap request size, tools are added in priority order until the budget is used. Tools found by `find_tools` come first, then by retrieval rank.
- **Multi-step requests:** "send an invoice for $50" needs create *and* send. If the second tool wasn't retrieved, the model calls `find_tools("send an existing invoice")`, and the match becomes callable on its next call.

**Alternatives considered:**

| Approach | Why not (here) |
|---|---|
| All tools in every call | ~369k tokens raw; doesn't fit most context windows, and near-identical tools confuse the model |
| An LLM picks the tools (LangChain's `LLMToolSelectorMiddleware`) | An extra model call per step, and the picker still reads every tool name, so it doesn't scale to thousands |
| Supervisor plus sub-agents | See section 1 |
| Code over a generated SDK | Strong for chaining many calls, but write actions are harder to put behind a per-call approval |

**Measured** (retrieval only, 63 held-out test cases): Recall@8 0.936, Recall@5 0.857, MRR 0.748, nDCG@5 0.747. Most misses are multi-step requests, which `find_tools` covers inside the agent.

## 3. State management

| State | Where it lives | Lifetime |
|---|---|---|
| A conversation's messages, approval pauses, `found_tools`, the last retrieval, injection flags | LangGraph state, checkpointed per `thread_id` | In memory |
| What the UI replays at `/atlas/<thread-id>` | A per-thread log of streamed events in `AtlasService` | In memory |
| "Status of my last request" | `runs/runlog.jsonl`, one line per turn | On disk |
| Traces | LangSmith, grouped by the same `thread_id` | Hosted |
| Account data | The mock PayPal, seeded from `seed.json` | In memory |

**How approvals work:** an approval is a LangGraph interrupt. The run stops with its state saved, and Approve or Reject resumes the same thread. One ID ties everything together: the URL, the checkpointer and LangSmith's thread view.

**For production:**
- **Persistence:** swap `InMemorySaver` for a Postgres checkpointer and keep transcripts in a table.
- **Per-user scoping:** scope the run log and threads per user. Today it's global, with no sign-in.

## 4. Scalability

**Not measured yet:** the catalog holds only PayPal's 115 tools. A test at 500–2,000 tools with lookalike services was planned and then dropped. What follows is argued from the design, not from a measured curve.

- **Request size doesn't grow with the catalog.** A call carries about 11 tool definitions (roughly 3–5k tokens) whether there are 115 tools or 2,000. Sending all 115 untrimmed would be about 369k.
- **Search stays cheap.** Qdrant grouped search over about 6 vectors per tool is milliseconds at this size and scales to millions with an approximate index. Adding a service means adding a spec folder plus a config line; there's no code branch per service.
- **What gets harder is lookalikes, not volume.** Stripe and Square also have "refund", "invoice" and "dispute". The design has three answers:
  - service-prefixed tool names (`stripe__invoices_create`),
  - a service filter in the search when the user or the session says which account,
  - curated keywords.

  Next steps, if accuracy dropped, would be a reranker or a larger embedding model.
- **How to prove it:** pad the catalog with other public OpenAPI specs to 500, 1,000 and 2,000 tools, and re-run the same retrieval eval (`atlas eval retrieval`) at each size.

## 5. Error handling

| Failure | Handling |
|---|---|
| The model sends inputs that break the tool's schema | The tool replies with the errors and the model retries; nested inputs sent as JSON strings are parsed first |
| The provider rejects the tool call before it runs (Groq) | `ToolCallRepairMiddleware` returns the reason to the model and retries up to twice |
| Per-minute rate limit or server error from the model | Retried with backoff (15 s, up to 60 s) |
| Daily quota | Not retried, because waiting won't help; the turn fails clearly |
| Backend 429 or 5xx | `ToolRetryMiddleware`, up to 3 retries |
| A tool the model needs isn't shown | `find_tools`, and the prompt says to search before giving up |
| Runaway loops | 8 model calls and 12 tool calls per turn |
| You reject a change | The model is told and doesn't retry the same change |
| An API outage during evals | Counted as a harness error, left out of the scores and flagged, so an outage can't look like a weak agent |

## 6. The RAG and system search tools

- **`rag_search`:** the merchant's handbook (refund, dispute, invoicing, subscription, shipping and webhook policies), chunked by heading into its own Qdrant collection. It returns passages with their sources, and the model answers from them.
- **`system_search`:** questions about Atlas itself. `scope="tools"` searches the same tool index ("what can you do with invoices?"). `scope="runs"` reads the run log ("what's the status of my last request?").

Both are always available, so they never depend on retrieval picking them.

## 7. Safety

- **Approval for every change:** write tools pause until you approve. This is the hard boundary.
- **Prompt injection:** tool results are untrusted. The prompt says to treat them as data. `InjectionGuardMiddleware` marks results containing instruction-like text ("ignore previous instructions", "you are now", "do not tell the user"…) as untrusted and flags the turn, and any approval in a flagged turn shows a warning. In a live test, an invoice whose note said to quietly refund $500 led to no refund, and Atlas told the user it had ignored the embedded instructions. The guard is a heuristic, which is why approval stays the real boundary.

## 8. Framework choice

| Option | Strength | Why not the core here |
|---|---|---|
| **LangChain `create_agent` (chosen)** | Built on LangGraph, so it has its state, checkpointing and interrupts. Middleware can change the tool list on every model call. Approval pauses, retries and limits come built in. | — |
| **LangGraph directly** | Full control over the graph | We'd rebuild middleware LangChain already ships. `create_agent` *is* LangGraph, so dropping down later is possible. |
| **LlamaIndex** | The strongest RAG toolkit: ingestion, retrievers, and even an object index for tool retrieval | Its agent runtime and tracing are a separate ecosystem. Our RAG need is small. Swapping `rag_search` to LlamaIndex later wouldn't touch the agent. |
| **CrewAI** | Role-based teams of agents | The opposite of this design (one agent with dynamic tools), with less control over which tools each call sees |
| **DSPy** | Optimises prompts and pipelines against a metric | A tuning tool, not a runtime. With 151 labelled cases and retrieval metrics, it's a good next step for tuning the system prompt or query rewriting. |
| **From scratch** | Total control, no dependency churn | Means rebuilding checkpoints, interrupts, streaming and tracing |

- **Observability:** LangSmith, which LangChain integrates natively. Every model and tool call is traced and grouped into one thread per conversation.
- **Retrieval stack:** Qdrant for its grouped search, with local bge-small embeddings. On the dev split, hybrid BM25 search lowered Recall@8 by 0.05–0.11, and bge-base was within noise.
- **Models:** the brief allowed any model. With a "free" constraint the agent ran on DeepSeek (OpenRouter), Gemini, Groq and now Gemma 4 locally. A provider registry makes each one a `.env` change.

## 9. Results

- **Retrieval only** (no LLM; 63 held-out cases): Recall@8 0.936, MRR 0.748. One caveat: curated keywords lifted Recall@8 from 0.921, and they were written knowing some test misses.
- **Full agent** (Groq gpt-oss-120b, 10 cases): 6 of 9 tasks completed and 100% tool execution success. One case was excluded as a provider error.
- **On Gemma 4 locally:** spot checks on the brief's three requests are correct, at about a minute per turn.

## 10. Known gaps

- **Scale:** not measured (section 4).
- **State:** everything except the run log is lost when the server restarts, and there are no users or sign-in.
- **Idempotency:** write calls carry no idempotency keys (`PayPal-Request-Id`), so a retried refund could repeat against a real API.
- **Policy limits:** these exist only in the handbook. "Refunds over $500 need the finance lead" isn't enforced in code.
- **Long conversations:** they aren't summarised, so the request budget eventually drops retrieved tools.
- **Speed:** about a minute per turn on a local 8B model, mostly prompt reading and thinking tokens.
