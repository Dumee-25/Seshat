export interface TimelineItem {
  ts: string;
  kind: "session" | "paper" | "artifact";
  id: number;
  title: string;
  subtitle?: string | null;
  meta: Record<string, unknown>;
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

export async function postChat(question: string): Promise<ChatResponse> {
  const res = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question }),
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
  return res.json() as Promise<ChatResponse>;
}

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

export async function addLink(url: string): Promise<PaperListItem> {
  const res = await fetch("/api/links", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url }),
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
  return res.json() as Promise<PaperListItem>;
}
