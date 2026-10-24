import { useState, type FormEvent, type KeyboardEvent } from "react";

interface Props {
  busy: boolean;
  disabled: boolean;
  onSend: (message: string) => void;
  onStop: () => void;
  placeholder: string;
}

export function Composer({ busy, disabled, onSend, onStop, placeholder }: Props) {
  const [text, setText] = useState("");

  function submit(event?: FormEvent) {
    event?.preventDefault();
    const message = text.trim();
    if (!message || busy || disabled) return;
    onSend(message);
    setText("");
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) submit();
  }

  return (
    <form className="composer panel" onSubmit={submit}>
      <label className="field">
        <span>Message</span>
        <textarea
          id="message"
          rows={3}
          maxLength={4000}
          value={text}
          placeholder={placeholder}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={onKeyDown}
          disabled={disabled}
        />
      </label>
      <div className="row">
        {busy ? (
          <button type="button" className="ghost" onClick={onStop}>
            Stop waiting
          </button>
        ) : (
          <button type="submit" className="primary" disabled={disabled || !text.trim()}>
            Send
          </button>
        )}
        <span className="hint">Ctrl or ⌘ + Enter</span>
      </div>
    </form>
  );
}
