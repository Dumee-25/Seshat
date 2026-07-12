import { useEffect, useState } from "react";
import {
  getFileChanges,
  getFileHistory,
  getFiles,
  type FileChange,
  type FileHistoryItem,
  type FileNode,
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
      <div
        className={`file-row${selected === node.path ? " selected" : ""}`}
        style={{ paddingLeft: depth * 14 + 10 }}
        onClick={() => onFile(node.path)}
      >
        <span className="file-name">{node.name}</span>
        {node.changes ? <span className="file-changes">{node.changes}</span> : null}
      </div>
    );
  }
  return (
    <div>
      <div
        className="dir-row"
        style={{ paddingLeft: depth * 14 + 4 }}
        onClick={() => setOpen((o) => !o)}
      >
        <span className="chevron">{open ? "▾" : "▸"}</span> {node.name}
      </div>
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

  useEffect(() => {
    getFiles().then(setTree).catch(() => {});
    getFileChanges().then(setChanges).catch(() => {});
  }, []);

  async function openFile(path: string) {
    setFile(path);
    setHistory(await getFileHistory(path));
  }

  return (
    <div className="code">
      <div className="code-tree">
        <div className="section-label">Files</div>
        {tree.length === 0 ? (
          <div className="empty">No watched code files.</div>
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
                <div
                  key={h.session_id}
                  className="hist-row"
                  onClick={() => onCite(h.session_id)}
                >
                  <span className="row-time">{when(h.started_at)}</span>
                  <span>{h.what_changed ?? `session ${h.session_id}`}</span>
                </div>
              ))
            )}
          </>
        ) : (
          <>
            <div className="section-label">Recent changes</div>
            {changes.length === 0 ? (
              <div className="empty">Nothing captured yet.</div>
            ) : (
              changes.map((c, i) => (
                <div
                  key={i}
                  className="change-row"
                  onClick={() => c.session_id && onCite(c.session_id)}
                >
                  <span className="mono change-path">{c.path}</span>
                  <span className="change-sum">{c.summary}</span>
                  <span className="row-time">{when(c.ts)}</span>
                </div>
              ))
            )}
          </>
        )}
      </div>
    </div>
  );
}
