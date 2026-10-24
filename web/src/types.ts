export type Access = "read" | "write";

export interface Hit {
  name: string;
  score: number;
}

export interface Retrieval {
  step: number;
  query: string;
  hits: Hit[];
  shown: string[];
  dropped: string[];
  found: string[];
}

export interface ApprovalRequest {
  name: string;
  args: Record<string, unknown>;
  description: string;
}

export type StreamEvent =
  | { type: "started"; thread_id: string }
  | ({ type: "retrieval" } & Retrieval)
  | { type: "tool_call"; id: string; name: string; args: Record<string, unknown>; access: Access }
  | { type: "tool_result"; id: string; name: string; status: number | null; body: unknown }
  | { type: "approval"; requests: ApprovalRequest[]; warning?: string }
  | { type: "token"; text: string }
  | { type: "message"; text: string }
  | { type: "done"; status: TurnStatus; trace_url: string | null; thread_url?: string | null }
  | { type: "error"; detail: string };

export type TurnStatus =
  | "running"
  | "awaiting_approval"
  | "completed"
  | "asked_user"
  | "limit_hit"
  | "error";

export interface ToolStep {
  kind: "tool";
  id: string;
  name: string;
  args: Record<string, unknown>;
  access: Access;
  result?: { status: number | null; body: unknown };
}

export type TimelineItem =
  | ({ kind: "retrieval" } & Retrieval)
  | ToolStep
  | { kind: "note"; text: string }
  | { kind: "decision"; approved: boolean; names: string[]; reason?: string };

export interface Turn {
  id: string;
  user: string;
  items: TimelineItem[];
  status: TurnStatus;
  answer?: string;
  approval?: ApprovalRequest[];
  approvalWarning?: string;
  draft?: string;
  traceUrl?: string | null;
  threadUrl?: string | null;
  error?: string;
}

export interface CatalogHit {
  name: string;
  score: number;
  rank: number;
  purpose: string;
  access: Access;
  group: string;
  method: string;
  path: string;
}

export interface StoredTurn {
  user: string;
  events: StreamEvent[];
}

export interface Transcript {
  thread_id: string;
  turns: StoredTurn[];
}

export interface Meta {
  model: string;
  tools: number;
  k: number;
  max_request_tokens: number | null;
  tracing: boolean;
}
