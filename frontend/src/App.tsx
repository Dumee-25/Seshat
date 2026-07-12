import { useEffect, useState } from "react";
import { getStatus, getTimeline, type Status, type TimelineItem } from "./api";
import { Chat } from "./Chat";
import { Timeline } from "./Timeline";

type View = "timeline" | "chat";

const STAR = (
  <svg width="18" height="18" viewBox="0 0 20 20" aria-hidden>
    <g stroke="var(--gold)" strokeWidth="1.4" strokeLinecap="round">
      {Array.from({ length: 7 }).map((_, i) => {
        const a = -Math.PI / 2 + (i * 2 * Math.PI) / 7;
        return (
          <line
            key={i}
            x1="10"
            y1="10"
            x2={(10 + 7.5 * Math.cos(a)).toFixed(1)}
            y2={(10 + 7.5 * Math.sin(a)).toFixed(1)}
          />
        );
      })}
    </g>
    <circle cx="10" cy="10" r="2" fill="var(--gold)" />
  </svg>
);

const PLACES = [
  { id: "timeline", label: "Timeline", ready: true },
  { id: "chat", label: "Chat", ready: true },
  { id: "papers", label: "Papers & links", ready: false },
  { id: "code", label: "Code", ready: false },
  { id: "data", label: "Data", ready: false },
];

export function App() {
  const [status, setStatus] = useState<Status | null>(null);
  const [items, setItems] = useState<TimelineItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<View>("timeline");
  const [highlight, setHighlight] = useState<number | null>(null);

  const jumpToSession = (sessionId: number) => {
    setHighlight(sessionId);
    setView("timeline");
  };

  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const [s, t] = await Promise.all([getStatus(), getTimeline()]);
        if (alive) {
          setStatus(s);
          setItems(t);
          setError(null);
        }
      } catch (e) {
        if (alive) setError(String(e));
      }
    };
    tick();
    const id = setInterval(tick, 5000); // simple live tail; SSE comes later
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          {STAR}
          <span className="wordmark">SESHAT</span>
        </div>
        {PLACES.map((p) => (
          <div
            key={p.id}
            className={`nav-item ${
              !p.ready ? "disabled" : view === p.id ? "active" : ""
            }`}
            onClick={() => p.ready && setView(p.id as View)}
          >
            <span>{p.label}</span>
            {!p.ready && <span className="nav-soon">soon</span>}
          </div>
        ))}
      </aside>

      <main className="main">
        {view === "timeline" ? (
          <>
            <h1 className="view-title">Timeline</h1>
            <div className="view-sub">
              {status ? status.project : "…"} · everything that has happened
            </div>
            {error ? (
              <div className="empty">
                Can't reach the Seshat API. Is the cockpit server running?
                <br />
                <span style={{ fontFamily: "var(--mono)", fontSize: 12 }}>
                  {error}
                </span>
              </div>
            ) : (
              <Timeline items={items} highlightId={highlight} />
            )}
          </>
        ) : (
          <>
            <h1 className="view-title">Chat</h1>
            <div className="view-sub">
              {status ? status.project : "…"} · ask across everything
            </div>
            <Chat onCite={jumpToSession} />
          </>
        )}
      </main>

      <footer className="statusbar">
        <span>
          <span className="dot" />
          {status ? "Connected" : "Connecting…"}
        </span>
        {status && <span>{status.sessions} sessions</span>}
        {status && <span>{status.queued} queued</span>}
        {status && <span>{status.papers} papers</span>}
      </footer>
    </div>
  );
}
