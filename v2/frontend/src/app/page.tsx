"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ChevronDown, Loader2, Search, Trash2 } from "lucide-react";
import { api, type AuditBrief } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { cn, scoreColor } from "@/lib/utils";

const CHECKS = [
  ["Technical", "Status codes, redirects, robots.txt, sitemaps, canonicals, HTTPS, duplicates"],
  ["On-page", "Titles, descriptions, headings, image alt text, Open Graph"],
  ["Content", "Thin & near-duplicate pages, readability, JS-only content"],
  ["Links", "Broken links, orphan pages, click depth, anchor text"],
  ["Performance", "Real-user Core Web Vitals (CrUX) kept separate from lab data"],
  ["Structured data", "JSON-LD validity and required properties per schema type"],
  ["AI search", "AI crawler access, extractable answers, entity & trust signals"],
  ["Competitors", "Side-by-side benchmark of on-site signals"],
];

export default function Home() {
  const router = useRouter();
  const [url, setUrl] = useState("");
  const [maxPages, setMaxPages] = useState(50);
  const [maxDepth, setMaxDepth] = useState(4);
  const [competitors, setCompetitors] = useState("");
  const [pagespeed, setPagespeed] = useState(true);
  const [advanced, setAdvanced] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [audits, setAudits] = useState<AuditBrief[] | null>(null);

  const load = () => api.listAudits().then(setAudits).catch(() => setAudits([]));
  useEffect(() => {
    load();
  }, []);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const comps = competitors.split(/[\n,]/).map((s) => s.trim()).filter(Boolean).slice(0, 3);
      const audit = await api.createAudit({ url, max_pages: maxPages, max_depth: maxDepth, competitors: comps, pagespeed });
      router.push(`/audits/${audit.id}`);
    } catch (err) {
      setError((err as Error).message);
      setSubmitting(false);
    }
  }

  return (
    <div className="space-y-8">
      <section className="mx-auto max-w-3xl pt-6 text-center">
        <h1 className="text-3xl font-bold tracking-tight sm:text-4xl">Find what&apos;s holding your site back in search</h1>
        <p className="mt-3 text-muted-foreground">
          A live crawl of your site across 8 audit areas, with every issue backed by evidence and ranked into a prioritised action plan.
        </p>
      </section>

      <Card className="mx-auto max-w-3xl">
        <CardContent className="pt-5">
          <form onSubmit={submit} className="space-y-4">
            <div className="flex flex-col gap-2 sm:flex-row">
              <Input required value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://yourstore.com" className="h-11 text-base" aria-label="Website URL" />
              <Button type="submit" size="lg" disabled={submitting || !url}>
                {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
                Run audit
              </Button>
            </div>
            <button type="button" onClick={() => setAdvanced((v) => !v)} className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
              <ChevronDown className={cn("h-4 w-4 transition-transform", advanced && "rotate-180")} /> Options & competitors
            </button>
            {advanced && (
              <div className="grid gap-4 sm:grid-cols-2">
                <label className="space-y-1 text-sm">
                  <span className="font-medium">Max pages to crawl</span>
                  <Input type="number" min={1} max={500} value={maxPages} onChange={(e) => setMaxPages(Number(e.target.value))} />
                </label>
                <label className="space-y-1 text-sm">
                  <span className="font-medium">Max click depth</span>
                  <Input type="number" min={0} max={10} value={maxDepth} onChange={(e) => setMaxDepth(Number(e.target.value))} />
                </label>
                <label className="space-y-1 text-sm sm:col-span-2">
                  <span className="font-medium">Competitor URLs (up to 3, comma or newline separated)</span>
                  <textarea
                    value={competitors}
                    onChange={(e) => setCompetitors(e.target.value)}
                    rows={2}
                    className="w-full rounded-md border bg-card px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    placeholder="competitor-one.com, competitor-two.com"
                  />
                </label>
                <label className="flex items-center gap-2 text-sm sm:col-span-2">
                  <input type="checkbox" checked={pagespeed} onChange={(e) => setPagespeed(e.target.checked)} />
                  Include Google PageSpeed Insights (real-user Core Web Vitals + Lighthouse lab run)
                </label>
              </div>
            )}
            {error && <p className="rounded-md bg-critical/10 px-3 py-2 text-sm text-critical">{error}</p>}
            <p className="text-xs text-muted-foreground">The crawler respects robots.txt and crawl-delay, rate-limits requests, and only audits public websites.</p>
          </form>
        </CardContent>
      </Card>

      <section className="mx-auto grid max-w-5xl gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {CHECKS.map(([t, d]) => (
          <div key={t} className="rounded-lg border bg-card p-4">
            <div className="text-sm font-semibold">{t}</div>
            <div className="mt-1 text-xs text-muted-foreground">{d}</div>
          </div>
        ))}
      </section>

      <Card className="mx-auto max-w-5xl">
        <CardHeader>
          <CardTitle>Recent audits</CardTitle>
          <CardDescription>Open any audit to see its dashboard and action plan.</CardDescription>
        </CardHeader>
        <CardContent>
          {audits === null ? (
            <p className="text-sm text-muted-foreground">Loading…</p>
          ) : audits.length === 0 ? (
            <p className="text-sm text-muted-foreground">No audits yet.</p>
          ) : (
            <ul className="divide-y">
              {audits.map((a) => (
                <li key={a.id} className="flex items-center gap-3 py-3">
                  <span className={cn("w-10 text-right text-lg font-bold tabular-nums", scoreColor(a.overall_score))}>{a.overall_score ?? "–"}</span>
                  <Link href={`/audits/${a.id}`} className="min-w-0 flex-1">
                    <div className="truncate font-medium hover:underline">{a.url}</div>
                    <div className="text-xs text-muted-foreground">{new Date(a.created_at).toLocaleString()}</div>
                  </Link>
                  <Badge className={cn(a.status === "completed" ? "bg-good/15 text-good" : a.status === "failed" ? "bg-critical/15 text-critical" : "bg-low/15 text-low")}>
                    {a.status}
                  </Badge>
                  {(a.status === "completed" || a.status === "failed") && (
                    <Button
                      variant="ghost"
                      size="sm"
                      aria-label="Delete audit"
                      onClick={async () => {
                        if (confirm(`Delete the audit of ${a.url}?`)) {
                          await api.deleteAudit(a.id);
                          load();
                        }
                      }}
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  )}
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
