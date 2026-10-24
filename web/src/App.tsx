import { useEffect, useMemo, useRef, useState } from "react";
import { getMeta, streamEvents } from "./api";
import { Composer } from "./components/Composer";
import { Header } from "./components/Header";
import { Inspector } from "./components/Inspector";
import { TurnView } from "./components/TurnView";
import { applyEvent, newTurn } from "./turns";
import type { Meta, Retrieval, Turn } from "./types";

export function App() {
  const [meta, setMeta] = useState<Meta | null>(null);
  const [apiUp, setApiUp] = useState<boolean | null>(null);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [threadId, setThreadId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [inspected, setInspected] = useState<{ turn: string; step: number } | null>(null);
  const controller = useRef<AbortController | null>(null);
  const end = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    getMeta()
      .then((m) => {
        setMeta(m);
        setApiUp(true);
      })
      .catch(() => setApiUp(false));
  }, []);

  useEffect(() => {
    end.current?.scrollIntoView({ block: "end", behavior: "smooth" });
  }, [turns]);

  const updateLast = (update: (turn: Turn) => Turn) =>
    setTurns((all) => (all.length ? [...all.slice(0, -1), update(all[all.length - 1])] : all));

  async function run(path: string, body: unknown) {
    const abort = new AbortController();
    controller.current = abort;
    setBusy(true);
    setInspected(null);
    try {
      await streamEvents(
        path,
        body,
        (event) => {
          if (event.type === "started") setThreadId(event.thread_id);
          else updateLast((turn) => applyEvent(turn, event));
        },
        abort.signal,
      );
    } catch (error) {
      const e = error as Error;
      const message =
        e.name === "AbortError" ? "Stopped waiting. The server may still finish this step." : e.message;
      updateLast((turn) => ({ ...turn, status: "error", error: message }));
    } finally {
      controller.current = null;
      setBusy(false);
    }
  }

  function send(message: string) {
    setTurns((all) => [...all, newTurn(message)]);
    void run("/api/chat/stream", { message, thread_id: threadId });
  }

  function decide(approved: boolean, reason?: string) {
    const last = turns.at(-1);
    if (!last?.approval || !threadId) return;
    const names = last.approval.map((r) => r.name);
    updateLast((turn) => ({
      ...turn,
      approval: undefined,
      status: "running",
      items: [...turn.items, { kind: "decision", approved, names, reason }],
    }));
    const decisions = names.map(() => (approved ? { type: "approve" } : { type: "reject", message: reason }));
    void run(`/api/chat/${threadId}/resume/stream`, { decisions });
  }

  function reset() {
    controller.current?.abort();
    setTurns([]);
    setThreadId(null);
    setInspected(null);
  }

  const retrieval = useMemo<Retrieval | null>(() => {
    const pool = inspected ? turns.filter((t) => t.id === inspected.turn) : turns.slice().reverse();
    for (const turn of pool) {
      const steps = turn.items.filter((i) => i.kind === "retrieval");
      const pick = inspected ? steps.find((s) => s.step === inspected.step) : steps.at(-1);
      if (pick) return pick;
    }
    return null;
  }, [turns, inspected]);

  const waitingForDecision = turns.at(-1)?.status === "awaiting_approval";

  return (
    <>
      <Header meta={meta} apiUp={apiUp} onNewConversation={reset} canReset={turns.length > 0} />
      <main className="layout">
        <section className="chat" aria-live="polite">
          {turns.length === 0 ? (
            <div className="empty panel">
              <h2>Ask Atlas about your PayPal account</h2>
              <p className="muted">
                Atlas has {meta?.tools ?? "115"} PayPal tools but shows the model only the{" "}
                {meta?.k ?? 8} that match each request. Watch which ones it picks in the Retrieval panel.
                Anything that changes data waits for your approval.
              </p>
            </div>
          ) : (
            turns.map((turn, i) => (
              <TurnView
                key={turn.id}
                turn={turn}
                busy={busy}
                isLast={i === turns.length - 1}
                onDecide={decide}
                onInspect={(step) => setInspected({ turn: turn.id, step })}
              />
            ))
          )}
          <Composer
            busy={busy}
            disabled={apiUp === false || waitingForDecision}
            onSend={send}
            onStop={() => controller.current?.abort()}
            placeholder={
              waitingForDecision
                ? "Approve or reject the change above first."
                : "What was my total sales volume last month?"
            }
          />
          <div ref={end} />
        </section>
        <Inspector retrieval={retrieval} />
      </main>
    </>
  );
}
