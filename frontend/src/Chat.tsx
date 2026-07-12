import { useEffect, useRef, useState } from "react";
import {
  clearChat,
  getChatHistory,
  postChat,
  type ChatMessage,
} from "./api";

export function Chat({ onCite }: { onCite: (sessionId: number) => void }) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    getChatHistory()
      .then(setMessages)
      .catch(() => {});
  }, []);
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, busy]);

  async function send() {
    const q = input.trim();
    if (!q || busy) return;
    setInput("");
    setError(null);
    setMessages((m) => [...m, { role: "user", text: q, citations: [] }]);
    setBusy(true);
    try {
      const res = await postChat(q);
      setMessages((m) => [
        ...m,
        { role: "assistant", text: res.answer, citations: res.citations },
      ]);
    } catch (e) {
      setError(String(e instanceof Error ? e.message : e));
    } finally {
      setBusy(false);
    }
  }

  async function onClear() {
    await clearChat();
    setMessages([]);
    setError(null);
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
            <div className="msg-text">{m.text}</div>
            {m.citations.length > 0 && (
              <div className="cites">
                {m.citations.map((c) => (
                  <button
                    key={c.session_id}
                    className="cite"
                    title={c.what_changed ?? ""}
                    onClick={() => onCite(c.session_id)}
                  >
                    session {c.session_id}
                  </button>
                ))}
              </div>
            )}
          </div>
        ))}
        {busy && (
          <div className="msg assistant">
            <div className="msg-text thinking">Thinking…</div>
          </div>
        )}
        <div ref={endRef} />
      </div>
      {error && <div className="chat-error">{error}</div>}
      <div className="chat-input">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && send()}
          placeholder="What did I already try?"
        />
        <button onClick={send} disabled={busy}>
          Ask
        </button>
        <button onClick={onClear} className="ghost">
          Clear
        </button>
      </div>
    </div>
  );
}
