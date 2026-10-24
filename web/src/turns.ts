import type { StoredTurn, StreamEvent, TimelineItem, Turn } from "./types";

export function applyEvent(turn: Turn, event: StreamEvent): Turn {
  switch (event.type) {
    case "retrieval": {
      const { type: _type, ...retrieval } = event;
      const step = turn.items.filter((item) => item.kind === "retrieval").length + 1;
      return { ...turn, items: [...turn.items, { kind: "retrieval", ...retrieval, step }] };
    }
    case "tool_call":
      if (turn.items.some((item) => item.kind === "tool" && item.id === event.id)) return turn;
      return {
        ...turn,
        items: [
          ...turn.items,
          { kind: "tool", id: event.id, name: event.name, args: event.args, access: event.access },
        ],
      };
    case "tool_result":
      return {
        ...turn,
        items: turn.items.map((item) =>
          item.kind === "tool" && item.id === event.id
            ? { ...item, result: { status: event.status, body: event.body } }
            : item,
        ),
      };
    case "token":
      return { ...turn, draft: (turn.draft ?? "") + event.text };
    case "message":
      return { ...turn, draft: undefined, items: [...turn.items, { kind: "note", text: event.text }] };
    case "approval":
      return {
        ...turn,
        draft: undefined,
        approval: event.requests,
        approvalWarning: event.warning,
        status: "awaiting_approval",
      };
    case "done":
      return finish({
        ...turn,
        draft: undefined,
        status: event.status,
        traceUrl: event.trace_url,
        threadUrl: event.thread_url ?? turn.threadUrl,
      });
    case "error":
      return { ...turn, status: "error", error: event.detail };
    default:
      return turn;
  }
}

function finish(turn: Turn): Turn {
  if (turn.status === "awaiting_approval") return turn;
  const last = turn.items.at(-1);
  if (last?.kind !== "note") return turn;
  return { ...turn, answer: last.text, items: turn.items.slice(0, -1) as TimelineItem[] };
}

export function replayTurn(stored: StoredTurn): Turn {
  return stored.events.reduce(applyEvent, newTurn(stored.user));
}

export function newTurn(user: string): Turn {
  return { id: crypto.randomUUID(), user, items: [], status: "running" };
}
