import type { Meta } from "../types";

interface Props {
  meta: Meta | null;
  apiUp: boolean | null;
  onNewConversation: () => void;
  canReset: boolean;
}

export function Header({ meta, apiUp, onNewConversation, canReset }: Props) {
  const status = apiUp === null ? "Checking API…" : apiUp ? "API online" : "API offline";
  return (
    <header className="top">
      <div>
        <p className="eyebrow">Tool-retrieval agent · PayPal REST API</p>
        <h1 className="brand">
          <img src="/atlas.svg" alt="" width={38} height={38} />
          Atlas
        </h1>
      </div>
      <div className="top__right">
        {meta && (
          <p className="meta-line">
            <span className="chip chip--neutral mono">{meta.model}</span>
            <span className="chip chip--info">
              top {meta.k} of {meta.tools} tools
            </span>
            {meta.max_request_tokens && (
              <span className="chip chip--neutral">
                {meta.max_request_tokens.toLocaleString()}-token budget
              </span>
            )}
          </p>
        )}
        <div className="top__actions">
          <button type="button" className="ghost" onClick={onNewConversation} disabled={!canReset}>
            New conversation
          </button>
          <p className={`api-status ${apiUp ? "is-up" : apiUp === false ? "is-down" : ""}`} role="status">
            <span className="dot" aria-hidden="true" />
            {status}
          </p>
        </div>
      </div>
    </header>
  );
}
