export interface TimelineItem {
  ts: string;
  kind: "session" | "paper" | "artifact";
  id: number;
  title: string;
  subtitle?: string | null;
  meta: Record<string, unknown>;
}

export type IntentStatus = "inferred" | "confirmed" | "corrected";

export interface IntentResult {
  id: number;
  intent: string;
  intent_status: IntentStatus;
}

export interface Status {
  project: string;
  root: string;
  sessions: number;
  queued: number;
  papers: number;
}

async function getJSON<T>(path: string): Promise<T> {
  const res = await fetch(path);
  if (!res.ok) throw new Error(`${path} -> ${res.status}`);
  return res.json() as Promise<T>;
}

/** POST JSON, surfacing FastAPI's `detail` as the error message when there is one. */
async function postJSON<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    let detail = `${res.status}`;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* keep status */
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

export const getStatus = () => getJSON<Status>("/api/status");

export const getTimeline = (kinds?: string) =>
  getJSON<{ items: TimelineItem[] }>(
    `/api/timeline${kinds ? `?kinds=${kinds}` : ""}`,
  ).then((r) => r.items);

export interface Citation {
  session_id: number;
  started_at: string;
  what_changed: string | null;
}

export interface ChatMessage {
  role: "user" | "assistant";
  text: string;
  ts?: string;
  citations: Citation[];
}

interface ChatResponse {
  answer: string;
  citations: Citation[];
  papers: { title: string; snippet: string; path: string }[];
}

export const getChatHistory = () =>
  getJSON<{ messages: ChatMessage[] }>("/api/chat/history").then(
    (r) => r.messages,
  );

export const postChat = (question: string) =>
  postJSON<ChatResponse>("/api/chat", { question });

/** Confirm an inferred intent (omit `intent`) or correct it (pass the new text). */
export const setIntent = (entryId: number, intent?: string) =>
  postJSON<IntentResult>(`/api/entries/${entryId}/intent`, { intent: intent ?? null });

export const clearChat = () => fetch("/api/chat/clear", { method: "POST" });

export interface PaperListItem {
  id: number;
  title: string | null;
  path: string;
  added_at: string | null;
  source: string;
}

export interface PaperDetail extends PaperListItem {
  content: string;
}

export const getPapers = () =>
  getJSON<{ papers: PaperListItem[] }>("/api/papers").then((r) => r.papers);

export const getPaper = (id: number) => getJSON<PaperDetail>(`/api/papers/${id}`);

export const addLink = (url: string) => postJSON<PaperListItem>("/api/links", { url });

export interface FileNode {
  name: string;
  path: string;
  type: "file" | "dir";
  changes?: number;
  last_changed?: string | null;
  children?: FileNode[];
}

export interface FileChange {
  path: string;
  kind: string;
  ts: string;
  session_id: number | null;
  summary: string;
}

export interface FileHistoryItem {
  session_id: number;
  started_at: string;
  what_changed: string | null;
}

export const getFiles = () =>
  getJSON<{ tree: FileNode[] }>("/api/files").then((r) => r.tree);

export const getFileChanges = () =>
  getJSON<{ changes: FileChange[] }>("/api/files/changes").then((r) => r.changes);

export const getFileHistory = (path: string) =>
  getJSON<{ sessions: FileHistoryItem[] }>(
    `/api/files/history?path=${encodeURIComponent(path)}`,
  ).then((r) => r.sessions);

export interface Artifact {
  id: number;
  path: string;
  name: string;
  kind: string;
  created_at: string | null;
}

export interface DataPreview {
  kind: "csv" | "json" | "text" | "missing";
  columns?: string[];
  rows?: string[][];
  text?: string;
  truncated?: boolean;
}

export interface DataDetail {
  artifact: { id: number; path: string; kind: string; created_at: string | null };
  preview: DataPreview;
  sessions: FileHistoryItem[];
}

export const getArtifacts = () =>
  getJSON<{ artifacts: Artifact[] }>("/api/data").then((r) => r.artifacts);

export const getArtifact = (id: number) => getJSON<DataDetail>(`/api/data/${id}`);
