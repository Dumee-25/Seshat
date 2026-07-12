import { useEffect, useState } from "react";
import {
  getArtifact,
  getArtifacts,
  type Artifact,
  type DataDetail,
  type DataPreview,
} from "./api";

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

  useEffect(() => {
    getArtifacts().then(setArtifacts).catch(() => {});
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

  return (
    <div>
      {artifacts.length === 0 ? (
        <div className="empty">
          No data tracked yet. CSV and JSON files in the project's results folder
          show up here.
        </div>
      ) : (
        <div className="paper-list">
          {artifacts.map((a) => (
            <div
              key={a.id}
              className="paper-row"
              onClick={() => getArtifact(a.id).then(setDetail)}
            >
              <span className="src pdf">{a.kind}</span>
              <span className="paper-title mono">{a.path}</span>
              <span className="paper-date">{when(a.created_at)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
