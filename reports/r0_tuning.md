# R0 retrieval tuning (dev split)

Run on 2026-10-24 against the 48 dev cases that need at least one indexed tool. Only the dev split was used for tuning; the test split stays held out.

| Examples per tool | Embedding model | Search | Recall@3 | Recall@5 | Recall@8 | MRR | nDCG@5 |
|---|---|---|---:|---:|---:|---:|---:|
| 5 | bge-small-en-v1.5 | dense | 0.740 | 0.875 | **0.948** | 0.720 | 0.722 |
| 5 | bge-small-en-v1.5 | hybrid (dense + BM25, RRF) | 0.615 | 0.677 | 0.833 | 0.662 | 0.610 |
| 5 | bge-base-en-v1.5 | dense | 0.792 | 0.854 | 0.938 | 0.777 | 0.750 |
| 5 | bge-base-en-v1.5 | hybrid | 0.708 | 0.760 | 0.885 | 0.660 | 0.639 |
| 10 | bge-small-en-v1.5 | dense | 0.760 | 0.802 | 0.927 | 0.780 | 0.739 |
| 10 | bge-small-en-v1.5 | hybrid | 0.656 | 0.823 | 0.906 | 0.643 | 0.660 |
| 10 | bge-base-en-v1.5 | dense | 0.823 | 0.865 | 0.927 | 0.776 | 0.767 |
| 10 | bge-base-en-v1.5 | hybrid | 0.635 | 0.719 | 0.885 | 0.606 | 0.594 |

An earlier pass also tried the bge query prefix on and off and a shorter head text per tool. Removing the prefix lowered Recall@8 by 0.01, and the head text made no difference.

## Decision

Kept **bge-small, 5 examples, dense only**: the best Recall@8 and the cheapest setup.

- **Hybrid search is worse on every row.** BM25 over short example sentences full of IDs and amounts adds noise, and rank fusion pulls in tools that share surface words.
- **bge-base and 10 examples** improve MRR a little but not Recall@8. With 48 cases, a 0.02 change is about one case, so it's within noise and not worth a model 3× larger.
- **Most remaining misses are multi-step requests** (one query, two or three tools). In the agent, `find_tools` lets the model search again for the next step, so that gap is measured as exposure recall in the full-agent runs, not here.
