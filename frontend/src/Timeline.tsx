import { useEffect, useRef, useState } from "react";
import { setIntent, type IntentStatus, type TimelineItem } from "./api";

const MARKER: Record<string, string> = {
  session: "var(--gold)",
  paper: "var(--faience)",
  artifact: "var(--muted)",
};

const FLASH_MS = 1700;

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

function IntentControls({
  item,
  onChange,
}: {
  item: TimelineItem;
  onChange: () => void;
}) {
  const entryId = item.meta.entry_id as number | undefined;
  const intent = item.meta.intent as string | null | undefined;
  const status = item.meta.intent_status as IntentStatus | undefined;

  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!intent || !status) return null;

  const conf = item.meta.intent_confidence as number | null | undefined;
  const label =
    status === "inferred" && conf != null ? `inferred · ${conf.toFixed(1)}` : status;

  const save = async (text?: string) => {
    if (entryId == null) return;
    setBusy(true);
    setError(null);
    try {
      await setIntent(entryId, text);
      setEditing(false);
      onChange();
    } catch (e) {
      setError(String(e instanceof Error ? e.message : e));
    } finally {
      setBusy(false);
    }
  };

  const editable = status === "inferred" && entryId != null;

  return (
    <>
      <span className={`badge ${status}`}>{label}</span>
      {editable && !editing && (
        <>
          <button className="link-btn confirm" disabled={busy} onClick={() => save()}>
            confirm
          </button>
          <button
            className="link-btn"
            disabled={busy}
            onClick={() => {
              setDraft(intent);
              setEditing(true);
            }}
          >
            edit
          </button>
        </>
      )}
      {editing && (
        <div className="intent-editor">
          <textarea
            value={draft}
            autoFocus
            onChange={(e) => setDraft(e.target.value)}
            placeholder="What were you actually trying to do?"
          />
          <div className="intent-actions">
            <button
              className="primary"
              disabled={busy || !draft.trim()}
              onClick={() => save(draft)}
            >
              Save
            </button>
            <button className="ghost" disabled={busy} onClick={() => setEditing(false)}>
              Cancel
            </button>
          </div>
          {error && <div className="chat-error">{error}</div>}
        </div>
      )}
    </>
  );
}

function Row({
  item,
  highlighted,
  flashing,
  onIntentChange,
}: {
  item: TimelineItem;
  highlighted: boolean;
  flashing: boolean;
  onIntentChange: () => void;
}) {
  const why = item.meta.intent as string | null | undefined;
  return (
    <div
      id={item.kind === "session" ? `tl-session-${item.id}` : undefined}
      className={`row${highlighted ? " highlighted" : ""}${flashing ? " flashing" : ""}`}
      style={{ ["--marker" as string]: MARKER[item.kind] }}
    >
      <div className="row-head">
        <span className="row-kind">{item.kind}</span>
        {item.kind === "session" && (
          <IntentControls item={item} onChange={onIntentChange} />
        )}
        <span className="row-time">{timeLabel(item.ts)}</span>
      </div>
      <div className="row-title">{item.title}</div>
      {item.subtitle && <div className="row-sub">{item.subtitle}</div>}
      {why && <div className="row-why">Why: {why}</div>}
    </div>
  );
}

export function Timeline({
  items,
  highlightId,
  onIntentChange,
}: {
  items: TimelineItem[];
  highlightId?: number | null;
  onIntentChange: () => void;
}) {
  const flashing = useNewItemFlash(items);

  useEffect(() => {
    if (highlightId != null) {
      document
        .getElementById(`tl-session-${highlightId}`)
        ?.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }, [highlightId, items]);

  if (items.length === 0) {
    return (
      <div className="empty">
        Nothing recorded yet. Run the watcher (or backfill) in a project, and
        activity appears here.
      </div>
    );
  }

  return (
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
                onIntentChange={onIntentChange}
              />
            );
          })}
        </div>
      ))}
    </div>
  );
}
