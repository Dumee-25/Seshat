import { useEffect, useState } from "react";
import {
  addLink,
  getPaper,
  getPapers,
  openExternal,
  type PaperDetail,
  type PaperListItem,
} from "./api";
import { Failed } from "./Failed";

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
  // True once the list has loaded at least once. Until then a failure means
  // the panel has nothing to show, and must say so rather than claim the
  // project has no papers.
  const [loaded, setLoaded] = useState(false);

  const load = () =>
    getPapers()
      .then((p) => {
        setPapers(p);
        setLoaded(true);
        setError(null);
      })
      .catch((e) => setError(String(e instanceof Error ? e.message : e)));
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
            // href is kept so copy-link and middle-click still work, but the
            // click is handled: the desktop window has no back button, so
            // following the link in place would strand the reader.
            <a
              href={selected.path}
              onClick={(e) => {
                e.preventDefault();
                openExternal(selected.path).catch((err) =>
                  setError(String(err instanceof Error ? err.message : err)),
                );
              }}
            >
              {selected.path}
            </a>
          ) : (
            <span>{selected.path}</span>
          )}
        </div>
        {error && <div className="chat-error">{error}</div>}
        <div className="reader-body">{selected.content || "(no extracted text)"}</div>
      </div>
    );
  }

  if (!loaded && error) return <Failed what="papers and links" detail={error} />;

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
          {loaded
            ? "No papers or links yet. Drop PDFs into the project's papers folder, or paste a URL above."
            : "Loading…"}
        </div>
      ) : (
        <div className="paper-list">
          {papers.map((p) => (
            <button
              key={p.id}
              className="paper-row"
              onClick={() => {
                setError(null); // don't carry a failed "add link" into the reader
                getPaper(p.id).then(setSelected).catch((e) => setError(String(e)));
              }}
            >
              <span className={`src ${p.source}`}>{p.source}</span>
              <span className="paper-title">{p.title || p.path}</span>
              <span className="paper-date">{when(p.added_at)}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
