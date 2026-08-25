import { useEffect, useState } from "react";
import {
  getArtifact,
  getArtifacts,
  type Artifact,
  type DataDetail,
  type DataPreview,
} from "./api";
import { Failed } from "./Failed";
import { ArrowLeft } from "./icons";

const SUMMARY_CHARS = 52;

/** What the session did, or its id if there is nothing better to say. */
function sessionLabel(whatChanged: string | null | undefined, id: number): string {
  const what = whatChanged?.trim();
  if (!what) return `session ${id}`;
  return what.length > SUMMARY_CHARS
    ? `${what.slice(0, SUMMARY_CHARS).trimEnd()}…`
    : what;
}

function when(ts: string | null): string {
  if (!ts) return "";
  const d = new Date(ts);
  return isNaN(d.getTime())
    ? ts
    : d.toLocaleString(undefined, {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      });
}

function Preview({ preview }: { preview: DataPreview }) {
  if (preview.kind === "missing")
    return <div className="empty">This file is no longer on disk.</div>;
  if (preview.kind === "csv")
    return (
      <div className="table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              {preview.columns!.map((c, i) => (
                <th key={i}>{c}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {preview.rows!.map((row, r) => (
              <tr key={r}>
                {row.map((cell, c) => (
                  <td key={c}>{cell}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        {preview.truncated && <div className="row-time">…truncated</div>}
      </div>
    );
  return <pre className="data-pre">{preview.text}</pre>;
}

export function Data({ onCite }: { onCite: (sessionId: number) => void }) {
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [detail, setDetail] = useState<DataDetail | null>(null);
  // See Code.tsx: a failed load must never fall through to an empty state
  // that claims the project has no data.
  const [loadError, setLoadError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    getArtifacts()
      .then((a) => {
        setArtifacts(a);
        setLoaded(true);
      })
      .catch((e) => setLoadError(String(e instanceof Error ? e.message : e)));
  }, []);

  if (detail) {
    return (
      <div className="reader">
        <button className="ghost back" onClick={() => setDetail(null)}>
          <ArrowLeft size={14} />
          Data
        </button>
        <h2 className="reader-title mono">{detail.artifact.path}</h2>
        {detail.sessions.length > 0 && (
          <>
            <div className="cites-head">
              <span>Produced by</span>
              <span className="cites-rule" />
            </div>
            <div className="produced-by">
              {/* Same chip as a chat citation, and for the same reason: the
                  session id says nothing about which run wrote this file. */}
              {detail.sessions.map((s) => (
                <button
                  key={s.session_id}
                  className="cite"
                  title={s.what_changed ?? `session ${s.session_id}`}
                  onClick={() => onCite(s.session_id)}
                >
                  <span className="cite-dot" />
                  <span>{sessionLabel(s.what_changed, s.session_id)}</span>
                </button>
              ))}
            </div>
          </>
        )}
        <Preview preview={detail.preview} />
      </div>
    );
  }

  if (loadError) return <Failed what="the data panel" detail={loadError} />;

  return (
    <div>
      {error && <div className="chat-error">{error}</div>}
      {artifacts.length === 0 ? (
        <div className="empty">
          {loaded
            ? "No data tracked yet. CSV and JSON files in the project's results folder show up here."
            : "Loading…"}
        </div>
      ) : (
        <div className="paper-list">
          {artifacts.map((a) => (
            <button
              key={a.id}
              className="paper-row"
              onClick={() => {
                setError(null);
                getArtifact(a.id)
                  .then(setDetail)
                  .catch((e) => setError(String(e instanceof Error ? e.message : e)));
              }}
            >
              {/* Its own quiet mono label. This used to borrow `src pdf` — the
                  gold PDF badge from Papers — so a CSV was labelled with
                  another surface's vocabulary. */}
              <span className="kind">{a.kind}</span>
              <span className="paper-title mono">{a.path}</span>
              <span className="paper-date">{when(a.created_at)}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
