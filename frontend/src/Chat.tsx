import { useEffect, useRef, useState } from "react";
import {
  clearChat,
  getChatHistory,
  postChat,
  type ChatMessage,
  type Citation,
} from "./api";
import { Markdown } from "./markdown";

const CITE_SUMMARY_CHARS = 52;

function citeDate(ts: string): string {
  const d = new Date(ts);
  return isNaN(d.getTime())
    ? ""
    : d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

/**
 * "Aug 1 · Added SMOTE oversampling…" rather than "session 12". The session
 * id means nothing to a reader deciding whether an answer is trustworthy;
 * when it happened and what it changed is the whole judgement.
 */
function citeParts(c: Citation): { date: string; summary: string } {
  const date = citeDate(c.started_at);
  const what = c.what_changed?.trim();
  if (!what) return { date: "", summary: date || `session ${c.session_id}` };
  const short =
    what.length > CITE_SUMMARY_CHARS
      ? `${what.slice(0, CITE_SUMMARY_CHARS).trimEnd()}…`
      : what;
  return { date, summary: short };
}

/** Seconds since a question went out, so local generation doesn't look frozen. */
function Elapsed() {
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setSeconds((s) => s + 1), 1000);
    return () => clearInterval(id);
  }, []);
  return <>Thinking{seconds >= 2 ? ` · ${seconds}s` : "…"}</>;
}

export function Chat({ onCite }: { onCite: (sessionId: number) => void }) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmClear, setConfirmClear] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);
  const boxRef = useRef<HTMLTextAreaElement>(null);
  const abort = useRef<AbortController | null>(null);

  useEffect(() => {
    getChatHistory()
      .then(setMessages)
      .catch(() => {});
  }, []);
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, busy]);

  // Abandon an in-flight question if the view goes away.
  useEffect(() => () => abort.current?.abort(), []);

  // Grow with the question, up to a point, then scroll inside.
  useEffect(() => {
    const box = boxRef.current;
    if (!box) return;
    box.style.height = "auto";
    box.style.height = `${Math.min(box.scrollHeight, 160)}px`;
  }, [input]);

  async function send() {
    const q = input.trim();
    if (!q || busy) return;
    setInput("");
    setError(null);
    setMessages((m) => [...m, { role: "user", text: q, citations: [] }]);
    setBusy(true);
    const controller = new AbortController();
    abort.current = controller;
    try {
      const res = await postChat(q, controller.signal);
      setMessages((m) => [
        ...m,
        { role: "assistant", text: res.answer, citations: res.citations },
      ]);
    } catch (e) {
      // A cancel is a choice, not a failure — don't report it as one.
      if (!controller.signal.aborted) {
        setError(String(e instanceof Error ? e.message : e));
      }
    } finally {
      abort.current = null;
      setBusy(false);
    }
  }

  async function onClear() {
    await clearChat();
    setMessages([]);
    setError(null);
    setConfirmClear(false);
  }

  return (
    <div className="chat">
      <div className="chat-log">
        {messages.length === 0 && !busy && (
          <div className="empty">
            Ask across your whole project — “have I tried SMOTE?”, “why did I
            drop region_code?”, “what did I do last week?”
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`msg ${m.role}`}>
            {m.role === "assistant" ? (
              <div className="msg-text">
                <Markdown text={m.text} />
              </div>
            ) : (
              <div className="msg-text">{m.text}</div>
            )}
            {m.citations.length > 0 && (
              <>
                {/* An answer's citations are its "check my work" links, so they
                    are labelled as such rather than left as a loose row of
                    chips under the prose. */}
                <div className="cites-head">
                  <span>Drawn from</span>
                  <span className="cites-rule" />
                </div>
                <div className="cites">
                  {m.citations.map((c) => {
                    const { date, summary } = citeParts(c);
                    return (
                      <button
                        key={c.session_id}
                        className="cite"
                        title={c.what_changed ?? `session ${c.session_id}`}
                        onClick={() => onCite(c.session_id)}
                      >
                        <span className="cite-dot" />
                        {date && <span className="cite-date">{date}</span>}
                        <span>{summary}</span>
                      </button>
                    );
                  })}
                </div>
              </>
            )}
          </div>
        ))}
        {busy && (
          <div className="msg assistant">
            <div className="msg-text thinking">
              <Elapsed />
            </div>
          </div>
        )}
        <div ref={endRef} />
      </div>
      {error && <div className="chat-error">{error}</div>}
      <div className="chat-input">
        <textarea
          ref={boxRef}
          rows={1}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              send();
            }
          }}
          placeholder="What did I already try?  (Shift+Enter for a new line)"
        />
        {busy ? (
          <button className="ghost" onClick={() => abort.current?.abort()}>
            Cancel
          </button>
        ) : (
          <button onClick={send} disabled={!input.trim()}>
            Ask
          </button>
        )}
        {/* Two steps, because one misclick here used to erase the conversation. */}
        {confirmClear ? (
          <>
            <button className="danger" onClick={onClear}>
              Erase all
            </button>
            <button className="ghost" onClick={() => setConfirmClear(false)}>
              Keep
            </button>
          </>
        ) : (
          <button
            className="ghost"
            disabled={messages.length === 0}
            onClick={() => setConfirmClear(true)}
          >
            Clear
          </button>
        )}
      </div>
    </div>
  );
}
