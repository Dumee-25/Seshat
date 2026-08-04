import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  getTimeline,
  resetIntent,
  setIntent,
  type IntentStatus,
  type TimelineItem,
} from "./api";
import { SessionDetail } from "./SessionDetail";

const MARKER: Record<string, string> = {
  session: "var(--gold)",
  paper: "var(--faience)",
  artifact: "var(--muted)",
};

const FLASH_MS = 1700;
const PAGE = 50;
const POLL_MS = 5000;
const SEARCH_DEBOUNCE_MS = 250;

const KINDS = ["session", "paper", "artifact"] as const;
type Kind = (typeof KINDS)[number];

const RANGES: { label: string; days: number | null }[] = [
  { label: "All time", days: null },
  { label: "7 days", days: 7 },
  { label: "30 days", days: 30 },
  { label: "90 days", days: 90 },
];

function sinceISO(days: number | null): string | undefined {
  if (days == null) return undefined;
  return new Date(Date.now() - days * 86_400_000).toISOString();
}

function startOfDay(d: Date): number {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
}

/** "Today" / "Yesterday" / "Jul 10" — and the year too, once it stops being obvious. */
function dayLabel(ts: string): string {
  const d = new Date(ts);
  if (isNaN(d.getTime())) return "Undated";
  const now = new Date();
  const days = Math.round((startOfDay(now) - startOfDay(d)) / 86_400_000);
  if (days === 0) return "Today";
  if (days === 1) return "Yesterday";
  return d.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    ...(d.getFullYear() === now.getFullYear() ? {} : { year: "numeric" }),
  });
}

function timeLabel(ts: string): string {
  const d = new Date(ts);
  if (isNaN(d.getTime())) return ts;
  return d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

interface Group {
  day: string;
  items: TimelineItem[];
}

function groupByDay(items: TimelineItem[]): Group[] {
  const groups: Group[] = [];
  for (const item of items) {
    const day = dayLabel(item.ts);
    if (groups.length === 0 || groups[groups.length - 1].day !== day) {
      groups.push({ day, items: [] });
    }
    groups[groups.length - 1].items.push(item);
  }
  return groups;
}

/**
 * Ids seen in a previous poll. Anything absent from it on a later render is
 * new activity and gets flashed — but the first load fills the set silently,
 * so opening the cockpit doesn't strobe the whole backlog.
 */
function useNewItemFlash(items: TimelineItem[]): Set<string> {
  const known = useRef<Set<string> | null>(null);
  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);
  const [flashing, setFlashing] = useState<Set<string>>(new Set());

  // Only unmount cancels a pending un-flash. Tying the timers to the effect's
  // cleanup would cancel them on the very next poll — and a poll can land
  // inside the flash window, since confirming an intent forces a refresh —
  // leaving the row flagged as new forever.
  useEffect(() => () => timers.current.forEach(clearTimeout), []);

  useEffect(() => {
    const keys = items.map((i) => `${i.kind}-${i.id}`);
    if (known.current === null) {
      known.current = new Set(keys); // first load: adopt, don't announce
      return;
    }
    const fresh = keys.filter((k) => !known.current!.has(k));
    keys.forEach((k) => known.current!.add(k));
    if (fresh.length === 0) return;
    setFlashing((f) => new Set([...f, ...fresh]));
    timers.current.push(
      setTimeout(() => {
        setFlashing((f) => {
          const next = new Set(f);
          fresh.forEach((k) => next.delete(k));
          return next;
        });
      }, FLASH_MS),
    );
  }, [items]);

  return flashing;
}

/** Delay a fast-changing value, so typing doesn't fire a request per keystroke. */
function useDebounced<T>(value: T, ms: number): T {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const id = setTimeout(() => setSettled(value), ms);
    return () => clearTimeout(id);
  }, [value, ms]);
  return settled;
}

/**
 * The review actions for one entry, held outside the controls so the row can
 * drive them from the keyboard as well as from its buttons.
 */
function useIntent(item: TimelineItem, onChange: () => void) {
  const entryId = item.meta.entry_id as number | undefined;
  const intent = item.meta.intent as string | null | undefined;
  const status = item.meta.intent_status as IntentStatus | undefined;

  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async (action: () => Promise<unknown>) => {
    if (entryId == null) return;
    setBusy(true);
    setError(null);
    try {
      await action();
      setEditing(false);
      onChange();
    } catch (e) {
      setError(String(e instanceof Error ? e.message : e));
    } finally {
      setBusy(false);
    }
  };

  return {
    intent,
    status,
    editing,
    setEditing,
    busy,
    error,
    reviewable: entryId != null && !!intent && !!status,
    unreviewed: status === "inferred",
    confidence: item.meta.intent_confidence as number | null | undefined,
    confirm: () => run(() => setIntent(entryId!)),
    correct: (text: string) => run(() => setIntent(entryId!, text)),
    undo: () => run(() => resetIntent(entryId!)),
  };
}

type Intent = ReturnType<typeof useIntent>;

function IntentControls({ ctl }: { ctl: Intent }) {
  const [draft, setDraft] = useState("");

  // The editor can be opened by key as well as by click, so the draft is
  // seeded on open rather than by whichever button did the opening.
  useEffect(() => {
    if (ctl.editing) setDraft(ctl.intent ?? "");
  }, [ctl.editing, ctl.intent]);

  if (!ctl.reviewable) return null;

  const label =
    ctl.unreviewed && ctl.confidence != null
      ? `inferred · ${ctl.confidence.toFixed(1)}`
      : ctl.status;

  return (
    <>
      <span className={`badge ${ctl.status}`}>{label}</span>
      {ctl.unreviewed && !ctl.editing && (
        <>
          <button
            className="link-btn confirm"
            disabled={ctl.busy}
            onClick={ctl.confirm}
          >
            confirm
          </button>
          <button
            className="link-btn"
            disabled={ctl.busy}
            onClick={() => ctl.setEditing(true)}
          >
            edit
          </button>
        </>
      )}
      {/* A third of guesses are expected to be wrong, so triage is fast and
          clicky — which is only safe if the click is reversible. */}
      {!ctl.unreviewed && (
        <button className="link-btn" disabled={ctl.busy} onClick={ctl.undo}>
          undo
        </button>
      )}
      {ctl.editing && (
        <div className="intent-editor">
          <textarea
            value={draft}
            autoFocus
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Escape") ctl.setEditing(false);
            }}
            placeholder="What were you actually trying to do?"
          />
          <div className="intent-actions">
            <button
              className="primary"
              disabled={ctl.busy || !draft.trim()}
              onClick={() => ctl.correct(draft)}
            >
              Save
            </button>
            <button
              className="ghost"
              disabled={ctl.busy}
              onClick={() => ctl.setEditing(false)}
            >
              Cancel
            </button>
          </div>
          {ctl.error && <div className="chat-error">{ctl.error}</div>}
        </div>
      )}
      {!ctl.editing && ctl.error && <div className="chat-error">{ctl.error}</div>}
    </>
  );
}

/** Move focus to the next/previous row, so triage never needs the mouse. */
function focusSibling(from: HTMLElement, delta: number) {
  const rows = [...document.querySelectorAll<HTMLElement>(".row[tabindex]")];
  const next = rows[rows.indexOf(from) + delta];
  next?.focus();
  next?.scrollIntoView({ block: "nearest" });
}

function Row({
  item,
  highlighted,
  flashing,
  expanded,
  onToggle,
  onIntentChange,
}: {
  item: TimelineItem;
  highlighted: boolean;
  flashing: boolean;
  expanded: boolean;
  onToggle: () => void;
  onIntentChange: () => void;
}) {
  const why = item.meta.intent as string | null | undefined;
  const isSession = item.kind === "session";
  const ctl = useIntent(item, onIntentChange);

  const onKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    // Only when the row itself has focus — never steal keys from the intent
    // editor or from a button inside the row.
    if (e.target !== e.currentTarget) return;
    const row = e.currentTarget;
    switch (e.key) {
      case "ArrowDown":
      case "j":
        e.preventDefault();
        return focusSibling(row, 1);
      case "ArrowUp":
      case "k":
        e.preventDefault();
        return focusSibling(row, -1);
      case "Enter":
      case " ":
        if (!isSession) return;
        e.preventDefault();
        return onToggle();
    }
    if (!ctl.reviewable || ctl.busy) return;
    if (e.key === "c" && ctl.unreviewed) {
      e.preventDefault();
      ctl.confirm();
    } else if (e.key === "e" && ctl.unreviewed) {
      e.preventDefault();
      ctl.setEditing(true);
    } else if (e.key === "u" && !ctl.unreviewed) {
      e.preventDefault();
      ctl.undo();
    }
  };

  return (
    <div
      id={isSession ? `tl-session-${item.id}` : undefined}
      className={`row${highlighted ? " highlighted" : ""}${flashing ? " flashing" : ""}`}
      style={{ ["--marker" as string]: MARKER[item.kind] }}
      tabIndex={0}
      onKeyDown={onKeyDown}
    >
      <div className="row-head">
        <span className="row-kind">{item.kind}</span>
        {isSession && <IntentControls ctl={ctl} />}
        <span className="row-time">{timeLabel(item.ts)}</span>
      </div>
      <div className="row-title">{item.title}</div>
      {item.subtitle && <div className="row-sub">{item.subtitle}</div>}
      {why && <div className="row-why">Why: {why}</div>}
      {isSession && (
        <button
          className="link-btn evidence-toggle"
          aria-expanded={expanded}
          onClick={onToggle}
        >
          {expanded ? "▾ hide evidence" : "▸ show evidence"}
        </button>
      )}
      {isSession && expanded && <SessionDetail sessionId={item.id} />}
    </div>
  );
}

export function Timeline({ highlightId }: { highlightId?: number | null }) {
  const [items, setItems] = useState<TimelineItem[]>([]);
  const [total, setTotal] = useState(0);
  const [limit, setLimit] = useState(PAGE);
  const [kinds, setKinds] = useState<Kind[]>([]);
  const [rangeDays, setRangeDays] = useState<number | null>(null);
  const [search, setSearch] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [expanded, setExpanded] = useState<Set<number>>(new Set());

  const debouncedSearch = useDebounced(search, SEARCH_DEBOUNCE_MS);
  const flashing = useNewItemFlash(items);

  // A narrowed feed is a different feed: start it from the top rather than
  // holding on to a page count grown for the previous filters.
  useEffect(() => {
    setLimit(PAGE);
  }, [debouncedSearch, kinds, rangeDays]);

  const since = useMemo(() => sinceISO(rangeDays), [rangeDays]);
  const kindsKey = kinds.join(",");

  const load = useCallback(async () => {
    try {
      const page = await getTimeline({
        limit,
        kinds,
        since,
        q: debouncedSearch,
      });
      setItems(page.items);
      setTotal(page.total);
      setError(null);
    } catch (e) {
      setError(String(e instanceof Error ? e.message : e));
    } finally {
      setLoaded(true);
    }
    // `kinds` is covered by kindsKey; depending on the array itself would
    // rebuild this callback on every render and restart the poll each time.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [limit, kindsKey, since, debouncedSearch]);

  useEffect(() => {
    load();
    const id = setInterval(load, POLL_MS); // simple live tail; SSE comes later
    return () => clearInterval(id);
  }, [load]);

  // A citation is a "check my work" link, so landing on the row opens the
  // evidence under it rather than stopping at what Seshat wrote.
  useEffect(() => {
    if (highlightId != null) {
      setExpanded((e) => new Set(e).add(highlightId));
    }
  }, [highlightId]);

  useEffect(() => {
    if (highlightId != null) {
      document
        .getElementById(`tl-session-${highlightId}`)
        ?.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }, [highlightId, items]);

  const toggleKind = (kind: Kind) =>
    setKinds((current) =>
      current.includes(kind)
        ? current.filter((k) => k !== kind)
        : [...current, kind],
    );

  const toggleRow = (id: number) =>
    setExpanded((current) => {
      const next = new Set(current);
      if (!next.delete(id)) next.add(id);
      return next;
    });

  const filtered = kinds.length > 0 || rangeDays != null || debouncedSearch.trim();

  const controls = (
    <div className="tl-controls">
      <input
        className="tl-search"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        placeholder="Search titles, outcomes, and intents…"
        aria-label="Search the timeline"
      />
      <div className="chips">
        {KINDS.map((kind) => (
          <button
            key={kind}
            className={`chip${kinds.includes(kind) ? " on" : ""}`}
            aria-pressed={kinds.includes(kind)}
            onClick={() => toggleKind(kind)}
          >
            {kind}
          </button>
        ))}
      </div>
      <select
        className="tl-range"
        value={String(rangeDays)}
        onChange={(e) =>
          setRangeDays(e.target.value === "null" ? null : Number(e.target.value))
        }
        aria-label="Time range"
      >
        {RANGES.map((r) => (
          <option key={r.label} value={String(r.days)}>
            {r.label}
          </option>
        ))}
      </select>
      <span className="tl-keys" aria-hidden="true">
        ↑↓ move · c confirm · e edit · u undo
      </span>
    </div>
  );

  let body;
  if (error && items.length === 0) {
    body = (
      <div className="empty">
        Can't reach the Seshat API. Is the cockpit server running?
        <br />
        <span className="mono">{error}</span>
      </div>
    );
  } else if (!loaded) {
    body = null;
  } else if (items.length === 0) {
    body = (
      <div className="empty">
        {filtered
          ? "Nothing matches these filters."
          : "Nothing recorded yet. Run the watcher (or backfill) in a project, and activity appears here."}
      </div>
    );
  } else {
    body = (
      <>
        <div className="feed">
          {groupByDay(items).map((group) => (
            <div key={group.day}>
              <div className="day-head">{group.day}</div>
              {group.items.map((item) => {
                const key = `${item.kind}-${item.id}`;
                return (
                  <Row
                    key={key}
                    item={item}
                    highlighted={item.kind === "session" && item.id === highlightId}
                    flashing={flashing.has(key)}
                    expanded={item.kind === "session" && expanded.has(item.id)}
                    onToggle={() => toggleRow(item.id)}
                    onIntentChange={load}
                  />
                );
              })}
            </div>
          ))}
        </div>
        <div className="tl-more">
          <span className="tl-count">
            {items.length} of {total}
          </span>
          {items.length < total && (
            <button className="ghost" onClick={() => setLimit((n) => n + PAGE)}>
              Load {Math.min(PAGE, total - items.length)} more
            </button>
          )}
        </div>
      </>
    );
  }

  return (
    <div className="timeline">
      {controls}
      <div className="tl-body">{body}</div>
    </div>
  );
}
