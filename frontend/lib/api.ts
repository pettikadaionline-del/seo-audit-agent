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
  created_at: string;
  overall_score: number | null;
  grade: string | null;
}

const ACCESS_KEY = "seo-audit:access-code";

export function getAccessCode(): string {
  try {
    return localStorage.getItem(ACCESS_KEY) ?? "";
  } catch {
    return "";
  }
}

export function setAccessCode(code: string) {
  try {
    localStorage.setItem(ACCESS_KEY, code);
  } catch {}
}

/** All calls go to this app's own /api proxy (app/api/[...path]/route.ts). */
async function post(path: string, body: unknown): Promise<Response> {
  const res = await fetch(`/api${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "x-access-code": getAccessCode() },
    body: JSON.stringify(body),
    cache: "no-store",
  });
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const data = await res.json();
      detail = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail);
    } catch {
      if (res.status === 504) detail = "The audit took too long. Try fewer pages or no competitors.";
    }
    throw new Error(detail);
  }
  return res;
}

export type ReportFormat = "json" | "csv" | "html" | "pdf";

export const api = {
  run: async (body: { url: string; max_pages?: number; competitors?: string[] }) =>
    (await post("/audit/run", body)).json() as Promise<Audit>,
  insights: async (audit: Audit) => (await post("/insights", audit)).json() as Promise<AIInsights>,
  /** Builds a report on the server from the stored result and triggers a download / new tab. */
  report: async (audit: Audit, fmt: ReportFormat, kind: "issues" | "pages" = "issues") => {
    const res = await post(`/report.${fmt}${fmt === "csv" ? `?kind=${kind}` : ""}`, audit);
    const url = URL.createObjectURL(await res.blob());
    // Popup blockers may refuse window.open after an await; fall back to a download.
    if (fmt !== "html" || !window.open(url, "_blank")) {
      const a = document.createElement("a");
      a.href = url;
      a.download = `seo-audit-${audit.id}${fmt === "csv" ? `-${kind}` : ""}.${fmt}`;
      a.click();
    }
    setTimeout(() => URL.revokeObjectURL(url), 60_000);
  },
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
