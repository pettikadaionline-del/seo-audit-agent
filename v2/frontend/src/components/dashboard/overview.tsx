import { Bot, CheckCircle2, Sparkles, XCircle } from "lucide-react";
import type { AuditResult } from "@/lib/api";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { cn, scoreColor } from "@/lib/utils";

export function ScoreRing({ score, grade, size = 140 }: { score: number; grade?: string; size?: number }) {
  const r = size / 2 - 10;
  const c = 2 * Math.PI * r;
  return (
    <div className="relative" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={r} stroke="var(--muted)" strokeWidth={10} fill="none" />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          strokeWidth={10}
          fill="none"
          strokeLinecap="round"
          stroke="currentColor"
          className={scoreColor(score)}
          strokeDasharray={c}
          strokeDashoffset={c * (1 - score / 100)}
        />
      </svg>
      <div className="absolute inset-0 grid place-items-center text-center">
        <div>
          <div className={cn("text-4xl font-bold tabular-nums", scoreColor(score))}>{score}</div>
          {grade && <div className="text-xs text-muted-foreground">Grade {grade}</div>}
        </div>
      </div>
    </div>
  );
}

export function CategoryGrid({ result, onSelect }: { result: AuditResult; onSelect?: (cat: string) => void }) {
  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      {Object.entries(result.categories).map(([key, c]) => (
        <button key={key} onClick={() => onSelect?.(key)} className="rounded-xl border bg-card p-4 text-left shadow-sm transition-colors hover:bg-muted">
          <div className="flex items-start justify-between gap-2">
            <div className="text-sm font-medium">{c.label}</div>
            <div className={cn("text-2xl font-bold tabular-nums", scoreColor(c.score))}>{c.score}</div>
          </div>
          <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-muted">
            <div className={cn("h-full rounded-full bg-current", scoreColor(c.score))} style={{ width: `${c.score}%` }} />
          </div>
          <div className="mt-2 flex flex-wrap gap-x-2 text-xs text-muted-foreground">
            <span>{c.findings} issue{c.findings === 1 ? "" : "s"}</span>
            {c.by_severity.critical > 0 && <span className="text-critical">{c.by_severity.critical} critical</span>}
            {c.by_severity.high > 0 && <span className="text-high">{c.by_severity.high} high</span>}
            <span className="ml-auto">weight {Math.round(c.weight * 100)}%</span>
          </div>
        </button>
      ))}
    </div>
  );
}

function Fact({ ok, label }: { ok: boolean; label: string }) {
  return (
    <div className="flex items-center gap-2 text-sm">
      {ok ? <CheckCircle2 className="h-4 w-4 text-good" /> : <XCircle className="h-4 w-4 text-critical" />}
      {label}
    </div>
  );
}

export function SiteFacts({ result }: { result: AuditResult }) {
  const s = result.summary;
  const ai = s.ai_crawler_access;
  return (
    <Card>
      <CardHeader>
        <CardTitle>Crawl facts</CardTitle>
        <CardDescription>
          {s.pages_crawled} URLs fetched · {s.pages_audited} indexable pages audited
          {s.skipped_over_limit > 0 && ` · ${s.skipped_over_limit} more not crawled (page limit)`}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-2">
        <Fact ok={s.https} label="Served over HTTPS" />
        <Fact ok={s.robots_txt} label="robots.txt present" />
        <Fact ok={s.sitemaps.length > 0} label={s.sitemaps.length ? `XML sitemap (${s.sitemap_urls} URLs)` : "XML sitemap"} />
        <Fact ok={s.llms_txt} label="llms.txt (optional, emerging)" />
        {ai && (
          <div className="pt-2">
            <div className="mb-1 flex items-center gap-1 text-xs font-medium text-muted-foreground">
              <Bot className="h-3.5 w-3.5" /> AI crawler access (robots.txt)
            </div>
            <div className="flex flex-wrap gap-1">
              {Object.entries(ai).map(([bot, ok]) => (
                <Badge key={bot} className={ok ? "bg-good/15 text-good" : "bg-critical/15 text-critical"}>
                  {bot}
                </Badge>
              ))}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export function SummaryCard({ result }: { result: AuditResult }) {
  const ai = result.ai;
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-2">
          <Sparkles className="h-4 w-4 text-primary" />
          <CardTitle>Executive summary</CardTitle>
          <Badge className={ai.source === "ai" ? "bg-primary/15 text-primary" : "bg-muted text-muted-foreground"}>
            {ai.source === "ai" ? "AI-generated" : "Rule-based"}
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <p className="text-sm leading-relaxed">{ai.executive_summary}</p>
        {ai.top_priorities.length > 0 && (
          <div>
            <div className="mb-1 text-sm font-medium">Do these first</div>
            <ol className="list-decimal space-y-1 pl-5 text-sm">
              {ai.top_priorities.map((p, i) => (
                <li key={i}>{p}</li>
              ))}
            </ol>
          </div>
        )}
        {ai.content_opportunities.length > 0 && (
          <div>
            <div className="mb-1 text-sm font-medium">Content opportunities</div>
            <ul className="space-y-1 text-sm">
              {ai.content_opportunities.map((o, i) => (
                <li key={i}>
                  <span className="font-medium">{o.title}</span> <span className="text-muted-foreground">– {o.rationale}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
        {ai.caveats.length > 0 && (
          <ul className="space-y-0.5 border-t pt-3 text-xs text-muted-foreground">
            {ai.caveats.map((c, i) => (
              <li key={i}>• {c}</li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
