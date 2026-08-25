import { useEffect, useState } from "react";
import { getSetup, getStatus, type SetupStatus, type Status } from "./api";
import { Chat } from "./Chat";
import { Code } from "./Code";
import { Data } from "./Data";
import { Health } from "./Health";
import { ICONS, Queue, Star } from "./icons";
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

const POLL_MS = 5000;
// Ollama's state changes on human timescales, and the check reaches out over
// HTTP — no reason to ask as often as we ask the store.
const SETUP_POLL_MS = 30000;

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

/** What the last poll actually did, rather than what it once managed to do. */
type Link = "connecting" | "live" | "lost";

function StatusBar({ link, status }: { link: Link; status: Status | null }) {
  const label =
    link === "live" ? "Connected" : link === "lost" ? "Not responding" : "Connecting…";

  // A queue that isn't draining looks broken unless it says why.
  let queuedNote = "";
  if (status && status.queued > 0) {
    queuedNote = status.gpu_busy
      ? " · waiting for the GPU"
      : status.cpu_fallback
        ? " · processing on CPU"
        : " · processing";
  }

  // Four equal spans made the one genuinely interesting state — why a stalled
  // queue is stalled — the hardest thing in the footer to notice. The counts
  // stay quiet on the left; a blocked queue gets weight and its own edge.
  const blocked = !!status && status.queued > 0;

  return (
    <footer className="statusbar">
      <span className="link">
        <span className={`dot ${link}`} />
        {label}
      </span>
      {status && <span className="sep" />}
      {status && <span>{status.sessions} sessions</span>}
      {status && <span className="dim">·</span>}
      {status && <span>{status.papers} papers</span>}
      {status && (
        <span
          className={`queue${blocked ? " blocked" : ""}`}
          title={
            status.queued === 0
              ? "Every captured session has a journal entry."
              : "Sessions captured but not yet journaled. Seshat waits for the GPU to be idle so it never competes with a training run."
          }
        >
          {blocked && <Queue />}
          {status.queued} queued{queuedNote}
        </span>
      )}
    </footer>
  );
}

export function App() {
  const [status, setStatus] = useState<Status | null>(null);
  const [link, setLink] = useState<Link>("connecting");
  const [setup, setSetup] = useState<SetupStatus | null>(null);
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
        if (!alive) return;
        setStatus(s);
        setLink("live");
      } catch {
        // Keep the last counts on screen — they are the most recent truth we
        // have — but stop claiming the connection is up.
        if (alive) setLink("lost");
      } finally {
        if (alive) setBooting(false);
      }
    };
    tick();
    const id = setInterval(tick, POLL_MS);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);

  useEffect(() => {
    let alive = true;
    const tick = () =>
      getSetup()
        .then((s) => alive && setSetup(s))
        .catch(() => {}); // the status bar already reports an unreachable API
    tick();
    const id = setInterval(tick, SETUP_POLL_MS);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);

  const scrolls = !SELF_SCROLLING.includes(view);

  return (
    <div className="app">
      <div className="app-body">
        <nav className="sidebar" aria-label="Views">
          <div className="brand">
            <Star />
            <span className="wordmark">SESHAT</span>
          </div>
          {PLACES.map((id) => {
            const Icon = ICONS[id];
            return (
              <button
                key={id}
                className={`nav-item${view === id ? " active" : ""}`}
                aria-current={view === id ? "page" : undefined}
                onClick={() => show(id)}
              >
                <span className="nav-icon">
                  <Icon />
                </span>
                <span>{TITLES[id][0]}</span>
              </button>
            );
          })}

          <div className="sidebar-foot">
            <div className="sidebar-foot-label">Project</div>
            <div className="sidebar-foot-name">
              {status ? status.project : "…"}
            </div>
          </div>
        </nav>

        <main className="main">
          {/* One band rather than a stacked title and subtitle: the old pair
              restated the nav item just clicked and cost ~66px of every
              surface — on the timeline, most of a row. The project name moved
              to the sidebar, where it belongs to the whole window. */}
          <div className="view-head">
            <h1 className="view-title">{TITLES[view][0]}</h1>
            <span className="view-sub">{TITLES[view][1]}</span>
          </div>

          {setup && !setup.ok && <Health setup={setup} />}

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

      <StatusBar link={link} status={status} />
    </div>
  );
}
