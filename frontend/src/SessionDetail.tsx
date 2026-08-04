/**
 * The evidence behind a journal entry.
 *
 * Seshat's argument for inferring intent at all is that a wrong guess is cheap
 * because you can check it. Checking it means reading the diffs the model read,
 * so a timeline row expands into exactly that: the raw events of the session,
 * rendered the way they were captured.
 */
import { useEffect, useState } from "react";
import { getSession, type RawEvent, type SessionDetailData } from "./api";

function timeLabel(ts: string): string {
  const d = new Date(ts);
  return isNaN(d.getTime())
    ? ts
    : d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

/** Classify a unified-diff line. File headers are not additions or deletions. */
function diffClass(line: string): string {
  if (line.startsWith("+++") || line.startsWith("---")) return "diff-file";
  if (line.startsWith("@@")) return "diff-hunk";
  if (line.startsWith("+")) return "diff-add";
  if (line.startsWith("-")) return "diff-del";
  return "diff-ctx";
}

function Diff({ text }: { text: string }) {
  if (!text.trim()) return <div className="ev-none">(no diff recorded)</div>;
  return (
    <pre className="diff">
      {text.split("\n").map((line, i) => (
        <div key={i} className={diffClass(line)}>
          {line || " "}
        </div>
      ))}
    </pre>
  );
}

function Outputs({ outputs }: { outputs?: string[] }) {
  if (!outputs?.length) return null;
  return (
    <div className="cell-outputs">
      {outputs.map((o, i) => (
        <div key={i} className="cell-output">
          {o}
        </div>
      ))}
    </div>
  );
}

interface Cell {
  source?: string;
  old_source?: string;
  outputs?: string[];
}

function NotebookDiff({ payload }: { payload: Record<string, unknown> }) {
  const added = (payload.added ?? []) as Cell[];
  const modified = (payload.modified ?? []) as Cell[];
  const removed = (payload.removed ?? []) as Cell[];
  const flags = [
    payload.kernel_restarted ? "kernel restarted" : null,
    payload.reordered ? "cells reordered" : null,
  ].filter(Boolean);

  return (
    <div className="nb-diff">
      {flags.length > 0 && <div className="nb-flags">{flags.join(" · ")}</div>}
      {added.map((cell, i) => (
        <div key={`a${i}`} className="cell">
          <div className="cell-label add">added cell</div>
          <pre className="cell-src diff-add">{cell.source}</pre>
          <Outputs outputs={cell.outputs} />
        </div>
      ))}
      {modified.map((cell, i) => (
        <div key={`m${i}`} className="cell">
          <div className="cell-label mod">modified cell</div>
          <pre className="cell-src diff-del">{cell.old_source}</pre>
          <pre className="cell-src diff-add">{cell.source}</pre>
          <Outputs outputs={cell.outputs} />
        </div>
      ))}
      {removed.map((cell, i) => (
        <div key={`r${i}`} className="cell">
          <div className="cell-label del">removed cell</div>
          <pre className="cell-src diff-del">{cell.source}</pre>
        </div>
      ))}
      {added.length + modified.length + removed.length === 0 &&
        flags.length === 0 && <div className="ev-none">(no cell changes)</div>}
    </div>
  );
}

function EventBody({ event }: { event: RawEvent }) {
  const p = event.payload;
  switch (event.kind) {
    case "notebook_diff":
      return <NotebookDiff payload={p} />;
    case "script_change":
      return <Diff text={(p.diff as string) ?? ""} />;
    case "git_commit":
      return (
        <>
          <div className="commit-msg">{(p.message as string) ?? ""}</div>
          {Array.isArray(p.files) && p.files.length > 0 && (
            <div className="commit-files mono">
              {(p.files as string[]).join(", ")}
            </div>
          )}
          <Diff text={(p.diff as string) ?? ""} />
        </>
      );
    case "result_file":
      return <pre className="ev-pre">{(p.preview as string) ?? ""}</pre>;
    default:
      return <pre className="ev-pre">{JSON.stringify(p, null, 2)}</pre>;
  }
}

export function SessionDetail({ sessionId }: { sessionId: number }) {
  const [detail, setDetail] = useState<SessionDetailData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    setDetail(null);
    setError(null);
    getSession(sessionId)
      .then((d) => alive && setDetail(d))
      .catch((e) => alive && setError(String(e instanceof Error ? e.message : e)));
    return () => {
      alive = false;
    };
  }, [sessionId]);

  if (error) return <div className="detail chat-error">{error}</div>;
  if (!detail) return <div className="detail ev-none">Loading evidence…</div>;

  const entry = detail.entries[0];

  return (
    <div className="detail">
      {entry && (
        <div className="detail-entry">
          {entry.observable_outcome && (
            <div className="detail-field">
              <span className="detail-key">Outcome</span>
              {entry.observable_outcome}
            </div>
          )}
          {entry.files_touched.length > 0 && (
            <div className="detail-field">
              <span className="detail-key">Files</span>
              <span className="mono">{entry.files_touched.join(", ")}</span>
            </div>
          )}
        </div>
      )}

      <div className="section-label">
        {detail.events.length === 0
          ? "No raw events"
          : `Raw events (${detail.events.length})`}
      </div>

      {detail.events.length === 0 ? (
        <div className="ev-none">
          Nothing was captured for this session — it predates the watcher, or
          came from backfilled history without diffs.
        </div>
      ) : (
        detail.events.map((event, i) => (
          <div key={i} className="ev">
            <div className="ev-head">
              <span className="ev-kind">{event.kind.replace("_", " ")}</span>
              {event.path && <span className="mono ev-path">{event.path}</span>}
              <span className="row-time">{timeLabel(event.ts)}</span>
            </div>
            <EventBody event={event} />
          </div>
        ))
      )}
    </div>
  );
}
