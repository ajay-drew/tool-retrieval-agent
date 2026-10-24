import { useState } from "react";
import type { ApprovalRequest } from "../types";
import { JsonBlock } from "./JsonBlock";

interface Props {
  requests: ApprovalRequest[];
  warning?: string;
  busy: boolean;
  onDecide: (approved: boolean, reason?: string) => void;
}

export function ApprovalPanel({ requests, warning, busy, onDecide }: Props) {
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState("");

  return (
    <section className="approval" aria-label="Approval needed">
      <p className="eyebrow">Needs your approval</p>
      {warning && <p className="notice notice--danger">{warning}</p>}
      <p>
        Atlas wants to make {requests.length === 1 ? "a change" : `${requests.length} changes`} to the
        account. Nothing runs until you decide.
      </p>
      {requests.map((request, i) => (
        <div className="approval__item" key={`${request.name}-${i}`}>
          <p className="mono">
            <span className="chip chip--warning">write</span> {request.name}
          </p>
          <JsonBlock label="Inputs" value={request.args} open />
        </div>
      ))}
      {rejecting ? (
        <form
          className="approval__reject"
          onSubmit={(e) => {
            e.preventDefault();
            onDecide(false, reason.trim() || "The user declined this change.");
          }}
        >
          <label className="field">
            <span>Why not? (sent to Atlas)</span>
            <input id="reject-reason" value={reason} onChange={(e) => setReason(e.target.value)} />
          </label>
          <div className="row">
            <button type="submit" className="danger" disabled={busy}>
              Reject
            </button>
            <button type="button" className="ghost" onClick={() => setRejecting(false)}>
              Back
            </button>
          </div>
        </form>
      ) : (
        <div className="row">
          <button type="button" className="primary" disabled={busy} onClick={() => onDecide(true)}>
            Approve
          </button>
          <button type="button" className="ghost" disabled={busy} onClick={() => setRejecting(true)}>
            Reject…
          </button>
        </div>
      )}
    </section>
  );
}
