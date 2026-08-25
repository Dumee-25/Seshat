import { useEffect, useState } from "react";
import {
  getFileChanges,
  getFileHistory,
  getFiles,
  type FileChange,
  type FileHistoryItem,
  type FileNode,
} from "./api";
import { Failed } from "./Failed";
import { Chevron } from "./icons";

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

function TreeNode({
  node,
  depth,
  selected,
  onFile,
}: {
  node: FileNode;
  depth: number;
  selected: string | null;
  onFile: (path: string) => void;
}) {
  const [open, setOpen] = useState(depth < 1);
  if (node.type === "file") {
    return (
      <button
        className={`file-row${selected === node.path ? " selected" : ""}`}
        style={{ paddingLeft: depth * 14 + 10 }}
        aria-current={selected === node.path ? "true" : undefined}
        onClick={() => onFile(node.path)}
      >
        <span className="file-name">{node.name}</span>
        {node.changes ? <span className="file-changes">{node.changes}</span> : null}
      </button>
    );
  }
  return (
    <div>
      <button
        className="dir-row"
        style={{ paddingLeft: depth * 14 + 4 }}
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
      >
        <span className="chevron">
          <Chevron open={open} />
        </span>
        {node.name}
      </button>
      {open &&
        node.children!.map((c) => (
          <TreeNode
            key={c.path}
            node={c}
            depth={depth + 1}
            selected={selected}
            onFile={onFile}
          />
        ))}
    </div>
  );
}

export function Code({ onCite }: { onCite: (sessionId: number) => void }) {
  const [tree, setTree] = useState<FileNode[]>([]);
  const [changes, setChanges] = useState<FileChange[]>([]);
  const [file, setFile] = useState<string | null>(null);
  const [history, setHistory] = useState<FileHistoryItem[]>([]);
  // Kept apart on purpose: a panel that could not load at all must not also
  // render "no watched code files", which asserts the opposite of the truth.
  const [loadError, setLoadError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    // Both or neither: a half-loaded panel that claims the project is empty
    // is worse than one that admits it could not read.
    Promise.all([getFiles(), getFileChanges()])
      .then(([t, c]) => {
        setTree(t);
        setChanges(c);
        setLoadError(null);
        setLoaded(true);
      })
      .catch((e) => setLoadError(String(e instanceof Error ? e.message : e)));
  }, []);

  async function openFile(path: string) {
    setFile(path);
    try {
      setHistory(await getFileHistory(path));
      setError(null);
    } catch (e) {
      setHistory([]);
      setError(String(e instanceof Error ? e.message : e));
    }
  }

  if (loadError) return <Failed what="the code panel" detail={loadError} />;

  return (
    <div className="code">
      <div className="code-tree">
        <div className="section-label">Files</div>
        {error && <div className="chat-error">{error}</div>}
        {tree.length === 0 ? (
          <div className="empty">{loaded ? "No watched code files." : "Loading…"}</div>
        ) : (
          tree.map((n) => (
            <TreeNode key={n.path} node={n} depth={0} selected={file} onFile={openFile} />
          ))
        )}
      </div>

      <div className="code-detail">
        {file ? (
          <>
            <div className="section-label mono">{file}</div>
            {history.length === 0 ? (
              <div className="empty">No recorded changes for this file yet.</div>
            ) : (
              history.map((h) => (
                <button
                  key={h.session_id}
                  className="hist-row"
                  onClick={() => onCite(h.session_id)}
                >
                  <span className="row-time">{when(h.started_at)}</span>
                  <span>{h.what_changed ?? `session ${h.session_id}`}</span>
                </button>
              ))
            )}
          </>
        ) : (
          <>
            <div className="section-label">Recent changes</div>
            {changes.length === 0 ? (
              <div className="empty">{loaded ? "Nothing captured yet." : "Loading…"}</div>
            ) : (
              changes.map((c, i) => (
                <button
                  key={i}
                  className="change-row"
                  disabled={c.session_id == null}
                  onClick={() => c.session_id && onCite(c.session_id)}
                >
                  <span className="mono change-path">{c.path}</span>
                  <span className="change-sum">{c.summary}</span>
                  <span className="row-time">{when(c.ts)}</span>
                </button>
              ))
            )}
          </>
        )}
      </div>
    </div>
  );
}
