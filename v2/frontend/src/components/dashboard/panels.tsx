"use client";

import { useEffect, useMemo, useState } from "react";
import { FlaskConical, Users } from "lucide-react";
import { api, type AuditResult, type FieldData, type PageRow, type SiteProfile } from "@/lib/api";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { cn, shortUrl } from "@/lib/utils";
import { SafeLink } from "./findings";

type SortKey = "url" | "status" | "depth" | "word_count" | "ttfb_ms" | "inbound_internal_links";

export function PagesTable({ auditId }: { auditId: string }) {
  const [rows, setRows] = useState<PageRow[] | null>(null);
  const [q, setQ] = useState("");
  const [sort, setSort] = useState<{ key: SortKey; dir: 1 | -1 }>({ key: "depth", dir: 1 });

  useEffect(() => {
    api.getPages(auditId).then((r) => setRows(r.items)).catch(() => setRows([]));
  }, [auditId]);

  const list = useMemo(() => {
    const items = (rows ?? []).filter((r) => !q || `${r.url} ${r.title ?? ""}`.toLowerCase().includes(q.toLowerCase()));
    return items.sort((a, b) => {
      const av = a[sort.key] ?? -1, bv = b[sort.key] ?? -1;
      return (av > bv ? 1 : av < bv ? -1 : 0) * sort.dir;
    });
  }, [rows, q, sort]);

  const th = (key: SortKey, label: string) => (
    <th className="cursor-pointer px-2 py-2 font-medium whitespace-nowrap hover:text-foreground" onClick={() => setSort((s) => ({ key, dir: s.key === key ? (-s.dir as 1 | -1) : 1 }))}>
      {label} {sort.key === key ? (sort.dir === 1 ? "↑" : "↓") : ""}
    </th>
  );

  return (
    <Card>
      <CardHeader className="flex-row flex-wrap items-center justify-between gap-2">
        <div>
          <CardTitle>Crawled pages</CardTitle>
          <CardDescription>{rows ? `${rows.length} URLs` : "Loading…"} · depth −1 = only found via sitemap</CardDescription>
        </div>
        <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Filter by URL or title…" className="h-9 max-w-xs" />
      </CardHeader>
      <CardContent className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead className="text-left text-muted-foreground">
            <tr className="border-b">
              {th("url", "URL")}
              {th("status", "Status")}
              {th("depth", "Depth")}
              <th className="px-2 py-2 font-medium">Title</th>
              {th("word_count", "Words")}
              {th("inbound_internal_links", "Inlinks")}
              {th("ttfb_ms", "TTFB")}
              <th className="px-2 py-2 font-medium">Schema</th>
              <th className="px-2 py-2 font-medium">Index</th>
            </tr>
          </thead>
          <tbody>
            {list.map((r) => (
              <tr key={r.url} className="border-b align-top last:border-0 hover:bg-muted/50">
                <td className="max-w-[260px] truncate px-2 py-1.5" title={r.url}>
                  <SafeLink url={r.url}>{shortUrl(r.url)}</SafeLink>
                </td>
                <td className={cn("px-2 py-1.5 tabular-nums", r.status && r.status >= 400 ? "text-critical" : r.redirects ? "text-medium" : "")}>
                  {r.status ?? r.error ?? "–"}
                  {r.redirects > 0 && ` (${r.redirects}↪)`}
                </td>
                <td className="px-2 py-1.5 tabular-nums">{r.depth}</td>
                <td className="max-w-[280px] truncate px-2 py-1.5" title={r.title ?? ""}>
                  {r.title ?? <span className="text-critical">missing</span>}
                </td>
                <td className="px-2 py-1.5 tabular-nums">{r.word_count}</td>
                <td className="px-2 py-1.5 tabular-nums">{r.inbound_internal_links ?? "–"}</td>
                <td className="px-2 py-1.5 tabular-nums">{r.ttfb_ms ? `${Math.round(r.ttfb_ms)} ms` : "–"}</td>
                <td className="max-w-[160px] truncate px-2 py-1.5">{r.schema_types.join(", ") || "–"}</td>
                <td className="px-2 py-1.5">{r.status === 200 ? (r.indexable ? "✓" : <span className="text-medium">noindex</span>) : "–"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </CardContent>
    </Card>
  );
}

const CAT_TONE: Record<string, string> = { FAST: "text-good", AVERAGE: "text-medium", SLOW: "text-critical" };
const CAT_LABEL: Record<string, string> = { FAST: "Good", AVERAGE: "Needs improvement", SLOW: "Poor" };

function FieldBlock({ title, data }: { title: string; data: FieldData }) {
  return (
    <div>
      <div className="mb-2 flex items-center gap-2 text-sm font-medium">
        {title}
        {data.overall && <Badge className={cn("bg-muted", CAT_TONE[data.overall])}>{CAT_LABEL[data.overall] ?? data.overall}</Badge>}
      </div>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
        {Object.entries(data.metrics).map(([k, m]) => (
          <div key={k} className="rounded-lg border p-3">
            <div className="text-xs text-muted-foreground">{k} (p75)</div>
            <div className={cn("text-lg font-semibold tabular-nums", m.category && CAT_TONE[m.category])}>
              {m.p75 == null ? "–" : k === "CLS" ? m.p75.toFixed(2) : `${Math.round(m.p75)} ${m.unit}`}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export function PerformancePanel({ result }: { result: AuditResult }) {
  const p = result.performance;
  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <Users className="h-4 w-4 text-primary" />
            <CardTitle>Real-user data (Chrome UX Report)</CardTitle>
          </div>
          <CardDescription>What actual Chrome visitors experienced over the last 28 days, at the 75th percentile. This is the data Google uses for Core Web Vitals.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {!p?.available ? (
            <p className="text-sm text-muted-foreground">PageSpeed Insights data not collected: {p?.error ?? "disabled"}. Crawler-based performance checks still ran (see findings).</p>
          ) : p.field_url || p.field_origin ? (
            <>
              {p.field_url && <FieldBlock title="This URL" data={p.field_url} />}
              {p.field_origin && <FieldBlock title="Whole origin" data={p.field_origin} />}
            </>
          ) : (
            <p className="text-sm text-muted-foreground">Google has no field data for this site (not enough Chrome traffic). Use the lab results below as an estimate only.</p>
          )}
        </CardContent>
      </Card>
      {p?.available && p.lab && (
        <Card>
          <CardHeader>
            <div className="flex items-center gap-2">
              <FlaskConical className="h-4 w-4 text-muted-foreground" />
              <CardTitle>Lab test (Lighthouse, simulated mobile)</CardTitle>
            </div>
            <CardDescription>One simulated run on a throttled device. Good for debugging; scores vary between runs and are not what users experience.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-6">
              <div className="rounded-lg border p-3">
                <div className="text-xs text-muted-foreground">Score</div>
                <div className="text-lg font-semibold">{p.lab.performance_score}</div>
              </div>
              {Object.entries(p.lab.metrics).map(([k, m]) => (
                <div key={k} className="rounded-lg border p-3">
                  <div className="text-xs text-muted-foreground">{k}</div>
                  <div className="text-lg font-semibold">{m.display}</div>
                </div>
              ))}
            </div>
            {p.lab.opportunities.length > 0 && (
              <ul className="space-y-1 text-sm">
                {p.lab.opportunities.map((o) => (
                  <li key={o.id} className="flex justify-between gap-4 border-b py-1 last:border-0">
                    <span>{o.title}</span>
                    <span className="text-muted-foreground tabular-nums">~{(o.savings_ms / 1000).toFixed(1)} s</span>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}

const ROWS: [keyof SiteProfile, string, (v: SiteProfile[keyof SiteProfile]) => string][] = [
  ["pages_crawled", "Pages sampled", String],
  ["sitemap_urls", "URLs in sitemap", String],
  ["median_word_count", "Median words / page", String],
  ["pct_with_schema", "Pages with structured data", (v) => `${v}%`],
  ["schema_types", "Schema types", (v) => (v as string[]).join(", ") || "–"],
  ["pct_with_meta_description", "Pages with meta description", (v) => `${v}%`],
  ["pct_with_single_h1", "Pages with exactly one H1", (v) => `${v}%`],
  ["pct_with_question_headings", "Pages with question headings", (v) => `${v}%`],
  ["pct_images_with_alt", "Images with alt text", (v) => `${v}%`],
  ["median_ttfb_ms", "Median TTFB", (v) => (v == null ? "–" : `${v} ms`)],
  ["has_faq_schema", "FAQ schema", (v) => (v ? "Yes" : "No")],
  ["ai_search_bots_allowed", "AI search bots allowed", (v) => (v ? "Yes" : "No")],
  ["llms_txt", "llms.txt", (v) => (v ? "Yes" : "No")],
];

export function CompetitorPanel({ result }: { result: AuditResult }) {
  const c = result.competitors;
  if (!c) {
    return <p className="text-sm text-muted-foreground">No competitors were added to this audit. Add up to 3 competitor URLs under &quot;Options&quot; when starting an audit.</p>;
  }
  const cols = [c.self, ...c.others];
  return (
    <Card>
      <CardHeader>
        <CardTitle>Competitive benchmark</CardTitle>
        <CardDescription>
          Light crawl (up to 15 pages) of each competitor, compared on observable on-site signals. Rankings, traffic and backlinks are not included; they need third-party data.
        </CardDescription>
      </CardHeader>
      <CardContent className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b text-left">
              <th className="py-2 pr-4 font-medium text-muted-foreground">Signal</th>
              {cols.map((s, i) => (
                <th key={s.url} className={cn("px-3 py-2 font-medium", i === 0 && "text-primary")}>
                  {i === 0 ? "You" : new URL(s.url).hostname}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {ROWS.map(([key, label, fmt]) => (
              <tr key={key} className="border-b last:border-0">
                <td className="py-2 pr-4 text-muted-foreground">{label}</td>
                {cols.map((s) => (
                  <td key={s.url} className="max-w-[220px] px-3 py-2">
                    {s.error ? <span className="text-xs text-critical">{s.error}</span> : fmt(s[key])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </CardContent>
    </Card>
  );
}
