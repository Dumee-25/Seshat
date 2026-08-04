import { useEffect, useState } from "react";
import {
  getArtifact,
  getArtifacts,
  type Artifact,
  type DataDetail,
  type DataPreview,
} from "./api";
import { Failed } from "./Failed";

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
          ← Data
        </button>
        <h2 className="reader-title mono">{detail.artifact.path}</h2>
        {detail.sessions.length > 0 && (
          <div className="produced-by">
            {detail.sessions.map((s) => (
              <button
                key={s.session_id}
                className="cite"
                title={s.what_changed ?? ""}
                onClick={() => onCite(s.session_id)}
              >
                session {s.session_id}
              </button>
            ))}
          </div>
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
              <span className="src pdf">{a.kind}</span>
              <span className="paper-title mono">{a.path}</span>
              <span className="paper-date">{when(a.created_at)}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
