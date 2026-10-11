"use client";

import { useMemo, useState } from "react";
import { ChevronRight } from "lucide-react";
import type { Action, ActionStatus, Advice, AuditResult, Finding } from "@/lib/api";
import { SeverityBadge, Badge } from "@/components/ui/badge";
import { Input, Select } from "@/components/ui/input";
import { cn } from "@/lib/utils";

export const STATUS_LABEL: Record<ActionStatus, string> = { todo: "To do", in_progress: "In progress", done: "Done", wont_fix: "Won't fix" };

export function StatusSelect({ action, onChange }: { action?: Action; onChange: (s: ActionStatus) => void }) {
  if (!action) return null;
  return (
    <Select value={action.status} onChange={(e) => onChange(e.target.value as ActionStatus)} onClick={(e) => e.stopPropagation()} aria-label="Action status">
      {Object.entries(STATUS_LABEL).map(([v, l]) => (
        <option key={v} value={v}>
          {l}
        </option>
      ))}
    </Select>
  );
}

// URLs come from the crawled site (including its robots.txt), so only http(s) becomes a link.
export function SafeLink({ url, children }: { url: string; children?: React.ReactNode }) {
  if (!/^https?:\/\//i.test(url)) return <span>{children ?? url}</span>;
  return (
    <a href={url} target="_blank" rel="noreferrer noopener" className="hover:underline">
      {children ?? url}
    </a>
  );
}

function EvidenceTable({ f }: { f: Finding }) {
  const keys = Array.from(new Set(f.evidence.flatMap((e) => Object.keys(e)).filter((k) => k !== "url")));
  const fmt = (v: unknown) => (v == null ? "–" : Array.isArray(v) ? v.join(", ") : typeof v === "object" ? JSON.stringify(v) : String(v));
  return (
    <div className="overflow-x-auto rounded-md border">
      <table className="w-full text-xs">
        <thead className="bg-muted text-left">
          <tr>
            <th className="px-2 py-1.5 font-medium">URL</th>
            {keys.map((k) => (
              <th key={k} className="px-2 py-1.5 font-medium">
                {k.replaceAll("_", " ")}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {f.evidence.map((e, i) => (
            <tr key={i} className="border-t align-top">
              <td className="max-w-xs break-all px-2 py-1.5">
                <SafeLink url={String(e.url)} />
              </td>
              {keys.map((k) => (
                <td key={k} className="max-w-xs break-words px-2 py-1.5">
                  {fmt(e[k])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {f.affected_urls.length > f.evidence.length && (
        <div className="border-t px-2 py-1.5 text-xs text-muted-foreground">
          Showing {f.evidence.length} of {f.affected_urls.length} affected URLs (export CSV/JSON for all).
        </div>
      )}
    </div>
  );
}

export function FindingDetail({ f, advice }: { f: Finding; advice?: Advice }) {
  return (
    <div className="space-y-3 px-1 pb-3 text-sm">
      <p>{advice?.why_it_matters || f.description}</p>
      {advice?.business_impact && <p className="text-muted-foreground italic">{advice.business_impact}</p>}
      <div>
        <div className="mb-1 font-medium">How to fix</div>
        <ol className="list-decimal space-y-1 pl-5">
          {(advice?.fix_steps?.length ? advice.fix_steps : [f.recommendation]).map((s, i) => (
            <li key={i}>{s}</li>
          ))}
        </ol>
      </div>
      {advice?.code_example && <pre className="overflow-x-auto rounded-md bg-muted p-3 text-xs">{advice.code_example}</pre>}
      <div className="flex flex-wrap gap-2 text-xs text-muted-foreground">
        <span>Check: {f.check_id}</span>·<span>Impact {f.priority.impact}/5</span>·<span>Effort {f.priority.effort}/5</span>·
        <span>Confidence: {f.confidence}</span>
      </div>
      <EvidenceTable f={f} />
    </div>
  );
}

export function FindingRow({
  f,
  advice,
  action,
  onStatus,
  defaultOpen = false,
}: {
  f: Finding;
  advice?: Advice;
  action?: Action;
  onStatus: (s: ActionStatus) => void;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className={cn("border-b last:border-0", action?.status === "done" && "opacity-60")}>
      <div className="flex cursor-pointer items-center gap-3 py-3" onClick={() => setOpen((o) => !o)}>
        <ChevronRight className={cn("h-4 w-4 shrink-0 text-muted-foreground transition-transform", open && "rotate-90")} />
        <SeverityBadge severity={f.severity} />
        <div className="min-w-0 flex-1">
          <div className={cn("text-sm font-medium", action?.status === "done" && "line-through")}>{f.title}</div>
          <div className="text-xs text-muted-foreground">
            {f.site_level ? "Site-wide" : `${f.affected_urls.length} page${f.affected_urls.length === 1 ? "" : "s"}`} · {f.id}
          </div>
        </div>
        <StatusSelect action={action} onChange={onStatus} />
      </div>
      {open && <FindingDetail f={f} advice={advice} />}
    </div>
  );
}

export function FindingsExplorer({
  result,
  actions,
  onStatus,
  category,
  setCategory,
}: {
  result: AuditResult;
  actions: Record<string, Action>;
  onStatus: (findingId: string, s: ActionStatus) => void;
  category: string;
  setCategory: (c: string) => void;
}) {
  const [severity, setSeverity] = useState("all");
  const [q, setQ] = useState("");
  const list = useMemo(
    () =>
      result.findings.filter(
        (f) =>
          (category === "all" || f.category === category) &&
          (severity === "all" || f.severity === severity) &&
          (!q || `${f.title} ${f.check_id} ${f.affected_urls.join(" ")}`.toLowerCase().includes(q.toLowerCase())),
      ),
    [result.findings, category, severity, q],
  );
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2">
        <Select value={category} onChange={(e) => setCategory(e.target.value)} aria-label="Category">
          <option value="all">All categories</option>
          {Object.entries(result.categories).map(([k, c]) => (
            <option key={k} value={k}>
              {c.label}
            </option>
          ))}
        </Select>
        <Select value={severity} onChange={(e) => setSeverity(e.target.value)} aria-label="Severity">
          <option value="all">All severities</option>
          {["critical", "high", "medium", "low", "info"].map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </Select>
        <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search issue or URL…" className="h-9 max-w-xs" />
        <Badge className="ml-auto self-center bg-muted">{list.length} findings</Badge>
      </div>
      <div className="rounded-xl border bg-card px-4">
        {list.length === 0 ? (
          <p className="py-6 text-center text-sm text-muted-foreground">No findings match these filters.</p>
        ) : (
          list.map((f) => <FindingRow key={f.id} f={f} advice={result.ai.findings[f.id]} action={actions[f.id]} onStatus={(s) => onStatus(f.id, s)} />)
        )}
      </div>
    </div>
  );
}
