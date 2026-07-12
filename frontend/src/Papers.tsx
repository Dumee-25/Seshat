import { useEffect, useState } from "react";
import {
  addLink,
  getPaper,
  getPapers,
  type PaperDetail,
  type PaperListItem,
} from "./api";

function when(ts: string | null): string {
  if (!ts) return "";
  const d = new Date(ts);
  return isNaN(d.getTime())
    ? ts
    : d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

export function Papers() {
  const [papers, setPapers] = useState<PaperListItem[]>([]);
  const [selected, setSelected] = useState<PaperDetail | null>(null);
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = () =>
    getPapers()
      .then(setPapers)
      .catch((e) => setError(String(e)));
  useEffect(() => {
    load();
  }, []);

  async function add() {
    const u = url.trim();
    if (!u || busy) return;
    setBusy(true);
    setError(null);
    try {
      await addLink(u);
      setUrl("");
      await load();
    } catch (e) {
      setError(String(e instanceof Error ? e.message : e));
    } finally {
      setBusy(false);
    }
  }

  if (selected) {
    return (
      <div className="reader">
        <button className="ghost back" onClick={() => setSelected(null)}>
          ← Papers &amp; links
        </button>
        <h2 className="reader-title">{selected.title}</h2>
        <div className="reader-meta">
          <span className={`src ${selected.source}`}>{selected.source}</span>
          {selected.source === "url" ? (
            <a href={selected.path}>{selected.path}</a>
          ) : (
            <span>{selected.path}</span>
          )}
        </div>
        <div className="reader-body">{selected.content || "(no extracted text)"}</div>
      </div>
    );
  }

  return (
    <div>
      <div className="addbar">
        <input
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && add()}
          placeholder="Paste a URL (arxiv, blog, docs) to add it…"
        />
        <button onClick={add} disabled={busy}>
          {busy ? "Adding…" : "Add link"}
        </button>
      </div>
      {error && <div className="chat-error">{error}</div>}
      {papers.length === 0 ? (
        <div className="empty">
          No papers or links yet. Drop PDFs into the project's papers folder, or
          paste a URL above.
        </div>
      ) : (
        <div className="paper-list">
          {papers.map((p) => (
            <div
              key={p.id}
              className="paper-row"
              onClick={() => getPaper(p.id).then(setSelected)}
            >
              <span className={`src ${p.source}`}>{p.source}</span>
              <span className="paper-title">{p.title || p.path}</span>
              <span className="paper-date">{when(p.added_at)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
