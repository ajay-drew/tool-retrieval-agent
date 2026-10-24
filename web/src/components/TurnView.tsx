import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { TimelineItem, Turn, TurnStatus } from "../types";
import { ApprovalPanel } from "./ApprovalPanel";
import { JsonBlock } from "./JsonBlock";

const STATUS: Record<TurnStatus, { label: string; tone: string }> = {
  running: { label: "Working", tone: "info" },
  awaiting_approval: { label: "Waiting for approval", tone: "warning" },
  completed: { label: "Done", tone: "success" },
  asked_user: { label: "Asked you a question", tone: "info" },
  limit_hit: { label: "Stopped at step limit", tone: "danger" },
  error: { label: "Failed", tone: "danger" },
};

function statusTone(status: number | null | undefined): string {
  if (status == null) return "neutral";
  if (status < 300) return "success";
  if (status < 500) return "warning";
  return "danger";
}

function Item({ item, onInspect }: { item: TimelineItem; onInspect: () => void }) {
  if (item.kind === "retrieval") {
    return (
      <li className="step step--retrieval">
        <div className="step__head">
          <span className="eyebrow">Step {item.step} · retrieval</span>
          <button type="button" className="link" onClick={onInspect}>
            Inspect
          </button>
        </div>
        <p className="small muted">
          Showed {item.shown.length} of {item.hits.length} retrieved tools
          {item.dropped.length > 0 && ` · ${item.dropped.length} dropped by the token budget`}
          {item.found.length > 0 && ` · ${item.found.length} added by find_tools`}
        </p>
        <div className="chips">
          {item.shown.map((name) => (
            <span key={name} className={`chip ${item.found.includes(name) ? "chip--info" : "chip--neutral"} mono`}>
              {name}
            </span>
          ))}
        </div>
      </li>
    );
  }
  if (item.kind === "tool") {
    const pending = item.result === undefined;
    return (
      <li className={`step step--tool ${pending ? "is-pending" : ""}`}>
        <div className="step__head">
          <span className="mono step__name">{item.name}</span>
          <span className={`chip chip--${item.access === "write" ? "warning" : "neutral"}`}>{item.access}</span>
          {pending ? (
            <span className="chip chip--info">running…</span>
          ) : (
            <span className={`chip chip--${statusTone(item.result?.status)}`}>{item.result?.status ?? "ok"}</span>
          )}
        </div>
        <JsonBlock label="Inputs" value={item.args} />
        {item.result && <JsonBlock label="Result" value={item.result.body} />}
      </li>
    );
  }
  if (item.kind === "decision") {
    return (
      <li className={`step step--decision ${item.approved ? "is-approved" : "is-rejected"}`}>
        <p className="small">
          {item.approved ? "You approved" : "You rejected"} <span className="mono">{item.names.join(", ")}</span>
          {item.reason && <span className="muted"> · “{item.reason}”</span>}
        </p>
      </li>
    );
  }
  return (
    <li className="step step--note">
      <p className="small muted">{item.text}</p>
    </li>
  );
}

interface Props {
  turn: Turn;
  busy: boolean;
  isLast: boolean;
  onDecide: (approved: boolean, reason?: string) => void;
  onInspect: (step: number) => void;
}

export function TurnView({ turn, busy, isLast, onDecide, onInspect }: Props) {
  const status = STATUS[turn.status];
  return (
    <article className="turn">
      <div className="bubble bubble--user">
        <p>{turn.user}</p>
      </div>
      {turn.items.length > 0 && (
        <ol className="timeline">
          {turn.items.map((item, i) => (
            <Item
              key={i}
              item={item}
              onInspect={() => item.kind === "retrieval" && onInspect(item.step)}
            />
          ))}
        </ol>
      )}
      {turn.status === "running" && (
        <p className="live-status" role="status">
          <span className="spinner" aria-hidden="true" />
          Atlas is working…
        </p>
      )}
      {turn.approval && turn.status === "awaiting_approval" && isLast && (
        <ApprovalPanel requests={turn.approval} busy={busy} onDecide={onDecide} />
      )}
      {turn.answer && (
        <div className="bubble bubble--agent">
          <Markdown remarkPlugins={[remarkGfm]}>{turn.answer}</Markdown>
        </div>
      )}
      {turn.error && <p className="notice notice--danger">{turn.error}</p>}
      {turn.status !== "running" && (
        <p className="turn__foot small">
          <span className={`chip chip--${status.tone}`}>{status.label}</span>
          {turn.traceUrl && (
            <a href={turn.traceUrl} target="_blank" rel="noreferrer">
              LangSmith trace ↗
            </a>
          )}
        </p>
      )}
    </article>
  );
}
