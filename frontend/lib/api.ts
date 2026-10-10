export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type Severity = "critical" | "high" | "medium" | "low" | "info";

export interface Issue {
  id: string;
  category: string;
  severity: Severity;
  title: string;
  description: string;
  recommendation: string;
  affected_urls: string[];
  evidence: Record<string, unknown>;
  impact: number;
  effort: "low" | "medium" | "high";
  priority_score: number;
}

export interface CategoryScore {
  category: string;
  score: number;
  issues: number;
  weight: number;
}

export interface PageSummary {
  url: string;
  status_code: number;
  title: string | null;
  word_count: number;
  response_time_ms: number;
  issues: number;
  depth: number;
}

export interface AIInsights {
  executive_summary: string;
  top_priorities: string[];
  quick_wins: string[];
  content_opportunities: string[];
  ai_search_recommendations: string[];
  roadmap_30_60_90: Record<string, string[]>;
  generated_by: string;
}

export interface Audit {
  id: string;
  url: string;
  status: "queued" | "crawling" | "analyzing" | "ai" | "completed" | "failed";
  progress: number;
  message: string;
  created_at: string;
  overall_score: number | null;
  grade: string | null;
  category_scores: CategoryScore[];
  issues: Issue[];
  pages: PageSummary[];
  competitors: Record<string, unknown>[];
  ai: AIInsights | null;
  stats: Record<string, any>;
  error: string | null;
}

export interface AuditListItem {
  id: string;
  url: string;
  status: string;
  created_at: string;
  overall_score: number | null;
  grade: string | null;
}

function headers(): HeadersInit {
  const key = process.env.NEXT_PUBLIC_API_KEY;
  return { "Content-Type": "application/json", ...(key ? { "X-API-Key": key } : {}) };
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, { ...init, headers: headers(), cache: "no-store" });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {}
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

export const api = {
  create: (body: { url: string; max_pages?: number; competitors?: string[]; use_ai?: boolean }) =>
    request<{ id: string }>("/api/audits", { method: "POST", body: JSON.stringify(body) }),
  list: () => request<AuditListItem[]>("/api/audits"),
  get: (id: string) => request<Audit>(`/api/audits/${id}`),
  reportUrl: (id: string, fmt: "json" | "csv" | "html" | "pdf", kind?: "issues" | "pages") =>
    `${API_URL}/api/audits/${id}/report.${fmt}${kind ? `?kind=${kind}` : ""}`,
};

const LABELS: Record<string, string> = {
  onpage: "On-Page",
  ai_readiness: "AI Readiness",
  structured_data: "Structured Data",
  links: "Internal Links",
  ai: "AI",
};

export const label = (s: string) =>
  LABELS[s] ?? s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
