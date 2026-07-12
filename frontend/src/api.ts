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
