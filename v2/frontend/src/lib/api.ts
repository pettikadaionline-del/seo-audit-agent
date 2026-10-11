export type Severity = "critical" | "high" | "medium" | "low" | "info";
export type Bucket = "critical" | "quick_win" | "strategic" | "long_term";
export type ActionStatus = "todo" | "in_progress" | "done" | "wont_fix";

export interface Finding {
  id: string;
  check_id: string;
  category: string;
  title: string;
  severity: Severity;
  description: string;
  recommendation: string;
  affected_urls: string[];
  evidence: Record<string, unknown>[];
  site_level: boolean;
  effort: number;
  confidence: string;
  priority: { impact: number; effort: number; bucket: Bucket; priority_score: number };
}

export interface CategoryScore {
  label: string;
  score: number;
  weight: number;
  findings: number;
  by_severity: Record<Severity, number>;
}

export interface Advice {
  why_it_matters: string;
  fix_steps: string[];
  code_example: string | null;
  business_impact: string;
}

export interface FieldMetric { p75: number | null; unit: string; category: string | null }
export interface FieldData { overall: string | null; metrics: Record<string, FieldMetric> }

export interface Performance {
  available: boolean;
  error?: string;
  url?: string;
  field_url?: FieldData | null;
  field_origin?: FieldData | null;
  lab?: {
    performance_score: number;
    metrics: Record<string, { value: number; display: string; score: number | null }>;
    opportunities: { id: string; title: string; savings_ms: number }[];
  };
}

export interface SiteProfile {
  url: string;
  pages_crawled: number;
  sitemap_urls: number;
  median_word_count: number;
  pct_with_schema: number;
  schema_types: string[];
  pct_with_meta_description: number;
  pct_with_single_h1: number;
  pct_with_question_headings: number;
  pct_images_with_alt: number;
  median_ttfb_ms: number | null;
  https: boolean;
  llms_txt: boolean;
  ai_search_bots_allowed: boolean;
  has_faq_schema: boolean;
  error: string | null;
}

export interface AuditResult {
  summary: {
    url: string;
    overall_score: number;
    grade: string;
    pages_crawled: number;
    pages_audited: number;
    html_pages: number;
    https: boolean;
    robots_txt: boolean;
    sitemaps: string[];
    sitemap_urls: number;
    llms_txt: boolean;
    ai_crawler_access: Record<string, boolean> | null;
    blocked_by_robots: number;
    skipped_over_limit: number;
  };
  categories: Record<string, CategoryScore>;
  findings: Finding[];
  buckets: Record<Bucket, { label: string; count: number }>;
  performance: Performance;
  competitors: { self: SiteProfile; others: SiteProfile[] } | null;
  ai: {
    source: "ai" | "rules";
    model?: string;
    executive_summary: string;
    top_priorities: string[];
    findings: Record<string, Advice>;
    content_opportunities: { title: string; rationale: string }[];
    caveats: string[];
  };
}

export interface AuditBrief {
  id: string;
  url: string;
  status: "queued" | "running" | "completed" | "failed";
  stage: string;
  progress: number;
  message: string;
  overall_score: number | null;
  error: string | null;
  created_at: string;
  completed_at: string | null;
}

export interface Audit extends AuditBrief {
  result: AuditResult | null;
}

export interface Action {
  id: number;
  finding_id: string;
  title: string;
  bucket: Bucket;
  status: ActionStatus;
  owner: string | null;
  notes: string | null;
}

export interface PageRow {
  url: string;
  status: number | null;
  depth: number | null;
  title: string | null;
  meta_description: string | null;
  h1: string[];
  word_count: number;
  ttfb_ms: number | null;
  html_bytes: number;
  indexable: boolean;
  canonical: string | null;
  schema_types: string[];
  internal_links_out: number;
  inbound_internal_links: number | null;
  images: number;
  redirects: number;
  error: string | null;
  in_sitemap: boolean;
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, { cache: "no-store", ...init, headers: { "content-type": "application/json", ...init?.headers } });
  if (!res.ok) {
    let msg = `Request failed (${res.status})`;
    try {
      const body = await res.json();
      msg = typeof body.detail === "string" ? body.detail : Array.isArray(body.detail) ? body.detail.map((d: { msg: string }) => d.msg).join("; ") : msg;
    } catch {}
    throw new Error(msg);
  }
  return res.status === 204 ? (undefined as T) : res.json();
}

export const api = {
  createAudit: (body: { url: string; max_pages: number; max_depth: number; competitors: string[]; pagespeed: boolean }) =>
    req<AuditBrief>("/audits", { method: "POST", body: JSON.stringify(body) }),
  listAudits: () => req<AuditBrief[]>("/audits"),
  getAudit: (id: string) => req<Audit>(`/audits/${id}`),
  getStatus: (id: string) => req<AuditBrief>(`/audits/${id}/status`),
  getPages: (id: string, q = "") => req<{ total: number; items: PageRow[] }>(`/audits/${id}/pages?limit=500${q ? `&q=${encodeURIComponent(q)}` : ""}`),
  getActions: (id: string) => req<Action[]>(`/audits/${id}/actions`),
  updateAction: (id: string, actionId: number, body: Partial<Pick<Action, "status" | "owner" | "notes">>) =>
    req<Action>(`/audits/${id}/actions/${actionId}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteAudit: (id: string) => req<void>(`/audits/${id}`, { method: "DELETE" }),
  exportUrl: (id: string, format: "json" | "csv" | "html") => `/api/audits/${id}/export?format=${format}`,
};
