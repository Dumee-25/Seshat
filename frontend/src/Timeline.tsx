import type { TimelineItem } from "./api";

const MARKER: Record<string, string> = {
  session: "var(--gold)",
  paper: "var(--faience)",
  artifact: "var(--muted)",
};

function when(ts: string): string {
  if (!ts) return "";
  const d = new Date(ts);
  if (isNaN(d.getTime())) return ts;
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function IntentBadge({ item }: { item: TimelineItem }) {
  if (item.kind !== "session") return null;
  const status = item.meta.intent_status as string | undefined;
  const intent = item.meta.intent as string | null | undefined;
  if (!intent || !status) return null;
  const conf = item.meta.intent_confidence as number | null | undefined;
  const label =
    status === "inferred" && conf != null
      ? `inferred · ${conf.toFixed(1)}`
      : status;
  return <span className={`badge ${status}`}>{label}</span>;
}

export function Timeline({ items }: { items: TimelineItem[] }) {
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
      {items.map((item) => (
        <div
          key={`${item.kind}-${item.id}`}
          className="row"
          style={{ ["--marker" as string]: MARKER[item.kind] }}
        >
          <div className="row-head">
            <span className="row-kind">{item.kind}</span>
            <IntentBadge item={item} />
            <span className="row-time">{when(item.ts)}</span>
          </div>
          <div className="row-title">{item.title}</div>
          {item.subtitle && <div className="row-sub">{item.subtitle}</div>}
        </div>
      ))}
    </div>
  );
}
