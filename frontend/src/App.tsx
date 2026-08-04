import { useEffect, useState } from "react";
import { getStatus, type Status } from "./api";
import { Chat } from "./Chat";
import { Code } from "./Code";
import { Data } from "./Data";
import { ICONS, Star } from "./icons";
import { Papers } from "./Papers";
import { Timeline } from "./Timeline";

type View = "timeline" | "chat" | "papers" | "code" | "data";

const TITLES: Record<View, [string, string]> = {
  timeline: ["Timeline", "everything that has happened"],
  chat: ["Chat", "ask across everything"],
  papers: ["Papers & links", "your reading, searchable"],
  code: ["Code", "files and their change history"],
  data: ["Data", "results and datasets"],
};

const PLACES: View[] = ["timeline", "chat", "papers", "code", "data"];

// These manage their own internal scrolling — the timeline so its filter bar
// stays put while the feed moves under it. The rest scroll as a page.
const SELF_SCROLLING: View[] = ["timeline", "chat", "code"];

const SKELETON_WIDTHS = [90, 72, 84, 60];

function Skeleton() {
  return (
    <div className="skeleton">
      {SKELETON_WIDTHS.map((w, i) => (
        <div
          key={i}
          className="skeleton-bar"
          style={{ width: `${w}%`, animationDelay: `${i * 0.12}s` }}
        />
      ))}
    </div>
  );
}

export function App() {
  const [status, setStatus] = useState<Status | null>(null);
  const [view, setView] = useState<View>("timeline");
  const [highlight, setHighlight] = useState<number | null>(null);
  // Held until the first poll resolves, so the skeleton stands in for the feed
  // rather than a flash of "nothing recorded yet".
  const [booting, setBooting] = useState(true);
  // Flips each view change so the enter animation restarts even when React
  // reuses the wrapper element.
  const [viewChanges, setViewChanges] = useState(0);

  const show = (next: View) => {
    setView(next);
    setViewChanges((n) => n + 1);
  };

  const jumpToSession = (sessionId: number) => {
    setHighlight(sessionId);
    show("timeline");
  };

  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const s = await getStatus();
        if (alive) setStatus(s);
      } catch {
        /* the timeline surfaces an unreachable API; the footer just waits */
      } finally {
        if (alive) setBooting(false);
      }
    };
    tick();
    const id = setInterval(tick, 5000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);

  const scrolls = !SELF_SCROLLING.includes(view);

  return (
    <div className="app">
      <div className="app-body">
        <aside className="sidebar">
          <div className="brand">
            <Star />
            <span className="wordmark">SESHAT</span>
          </div>
          {PLACES.map((id) => {
            const Icon = ICONS[id];
            return (
              <div
                key={id}
                className={`nav-item${view === id ? " active" : ""}`}
                onClick={() => show(id)}
                title={TITLES[id][0]}
              >
                <span className="nav-icon">
                  <Icon />
                </span>
                <span>{TITLES[id][0]}</span>
              </div>
            );
          })}
        </aside>

        <main className="main">
          <h1 className="view-title">{TITLES[view][0]}</h1>
          <div className="view-sub">
            {status ? status.project : "…"} · {TITLES[view][1]}
          </div>

          <div
            key={viewChanges}
            className={`content${scrolls ? " scrolls" : ""}`}
          >
            {booting ? (
              <Skeleton />
            ) : (
              <>
                {view === "timeline" && <Timeline highlightId={highlight} />}
                {view === "chat" && <Chat onCite={jumpToSession} />}
                {view === "papers" && <Papers />}
                {view === "code" && <Code onCite={jumpToSession} />}
                {view === "data" && <Data onCite={jumpToSession} />}
              </>
            )}
          </div>
        </main>
      </div>

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
