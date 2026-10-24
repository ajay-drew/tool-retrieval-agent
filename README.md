# Atlas

A chat agent that stays accurate with 100+ API tools. On every model call, Atlas searches its tool list and gives the model only the tools that match the request. Phase 1 uses PayPal's 115 REST operations; an eval harness measures how well it picks tools and fills in their inputs.

Built on LangChain `create_agent`, DeepSeek v4-flash through OpenRouter, local bge-small embeddings and FAISS, with LangSmith for tracing and evals.

Status: in progress. See [plan.md](plan.md) for the build plan and [architecture.md](architecture.md) for the design.

## Quickstart

```bash
uv sync
cp .env.example .env   # add OPENROUTER_API_KEY and LANGSMITH_API_KEY
uv run atlas smoke     # one model tool call, traced in LangSmith
```

## License

MIT. PayPal's OpenAPI specs under `specs/paypal/` keep their own Apache-2.0 license.
