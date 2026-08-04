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

export interface TimelineQuery {
  kinds?: string[];
  since?: string;
  q?: string;
  limit?: number;
  offset?: number;
}

export interface TimelinePage {
  items: TimelineItem[];
  /** Matches in the whole store, not just this page — drives "load more". */
  total: number;
}

export const getTimeline = (opts: TimelineQuery = {}) => {
  const params = new URLSearchParams();
  if (opts.kinds?.length) params.set("kinds", opts.kinds.join(","));
  if (opts.since) params.set("since", opts.since);
  if (opts.q?.trim()) params.set("q", opts.q.trim());
  if (opts.limit != null) params.set("limit", String(opts.limit));
  if (opts.offset != null) params.set("offset", String(opts.offset));
  const qs = params.toString();
  return getJSON<TimelinePage>(`/api/timeline${qs ? `?${qs}` : ""}`);
};

/** A raw event exactly as captured — the evidence behind a journal entry. */
export interface RawEvent {
  ts: string;
  kind: string;
  path: string | null;
  payload: Record<string, unknown>;
}

export interface EntryDetail {
  id: number;
  what_changed: string;
  observable_outcome: string | null;
  inferred_intent: string | null;
  intent_status: IntentStatus;
  intent_confidence: number | null;
  files_touched: string[];
}

export interface SessionDetailData {
  session: {
    id: number;
    started_at: string;
    ended_at: string | null;
    status: string;
  };
  entries: EntryDetail[];
  events: RawEvent[];
}

export const getSession = (id: number) =>
  getJSON<SessionDetailData>(`/api/sessions/${id}`);

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
