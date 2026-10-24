import { useEffect, useState } from "react";
import { searchTools } from "../api";
import type { CatalogHit, Retrieval } from "../types";

function ScoreBar({ score, max }: { score: number; max: number }) {
  const width = max > 0 ? Math.max(4, (score / max) * 100) : 0;
  return (
    <span className="score" aria-label={`score ${score.toFixed(3)}`}>
      <span className="score__bar" style={{ width: `${width}%` }} />
      <span className="score__num mono">{score.toFixed(3)}</span>
    </span>
  );
}

function LastRetrieval({ retrieval }: { retrieval: Retrieval | null }) {
  if (!retrieval) {
    return <p className="muted small">Send a message to see which tools retrieval picks for each model call.</p>;
  }
  const max = Math.max(...retrieval.hits.map((h) => h.score), 0);
  const extra = retrieval.found.filter((name) => !retrieval.hits.some((h) => h.name === name));
  return (
    <div className="retrieval">
      <p className="small">
        <span className="muted">Step {retrieval.step} searched for</span> “{retrieval.query}”
      </p>
      <ol className="hits">
        {retrieval.hits.map((hit) => {
          const state = retrieval.shown.includes(hit.name)
            ? "shown"
            : retrieval.dropped.includes(hit.name)
              ? "dropped"
              : "hidden";
          return (
            <li key={hit.name} className={`hit hit--${state}`}>
              <span className="mono hit__name">{hit.name}</span>
              <ScoreBar score={hit.score} max={max} />
              <span className={`chip chip--${state === "shown" ? "success" : state === "dropped" ? "warning" : "neutral"}`}>
                {state === "shown" ? "shown" : state === "dropped" ? "over budget" : "not shown"}
              </span>
            </li>
          );
        })}
        {extra.map((name) => (
          <li key={name} className="hit hit--found">
            <span className="mono hit__name">{name}</span>
            <span />
            <span className="chip chip--info">find_tools</span>
          </li>
        ))}
      </ol>
    </div>
  );
}

function CatalogSearch() {
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<CatalogHit[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const q = query.trim();
    if (q.length < 3) {
      setHits([]);
      return;
    }
    const controller = new AbortController();
    const timer = setTimeout(() => {
      searchTools(q, 10, controller.signal)
        .then((result) => {
          setHits(result);
          setError(null);
        })
        .catch((e: Error) => e.name !== "AbortError" && setError(e.message));
    }, 300);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [query]);

  const max = Math.max(...hits.map((h) => h.score), 0);
  return (
    <div className="catalog">
      <label className="field">
        <span>Try a request against the catalog</span>
        <input
          id="catalog-query"
          type="search"
          value={query}
          placeholder="refund a payment"
          onChange={(e) => setQuery(e.target.value)}
        />
      </label>
      {error && <p className="notice notice--danger small">{error}</p>}
      <ol className="hits">
        {hits.map((hit) => (
          <li key={hit.name} className="hit hit--catalog">
            <div className="hit__main">
              <span className="mono hit__name">{hit.name}</span>
              <span className={`chip chip--${hit.access === "write" ? "warning" : "neutral"}`}>{hit.access}</span>
            </div>
            <ScoreBar score={hit.score} max={max} />
            <p className="small muted hit__purpose">{hit.purpose}</p>
            <p className="mono hit__path">
              {hit.method} {hit.path}
            </p>
          </li>
        ))}
      </ol>
    </div>
  );
}

export function Inspector({ retrieval }: { retrieval: Retrieval | null }) {
  return (
    <aside className="side">
      <section className="panel">
        <h2>Retrieval</h2>
        <p className="muted small">What the model was allowed to see on this call, out of the whole catalog.</p>
        <LastRetrieval retrieval={retrieval} />
      </section>
      <section className="panel">
        <h2>Search the catalog</h2>
        <CatalogSearch />
      </section>
    </aside>
  );
}
