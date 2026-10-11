"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { AlertTriangle, Download, FileText, Loader2, RefreshCw } from "lucide-react";
import { AccessCodeError, api, type Action, type ActionStatus, type Audit } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { CategoryGrid, ScoreRing, SiteFacts, SummaryCard } from "@/components/dashboard/overview";
import { ActionPlan } from "@/components/dashboard/action-plan";
import { FindingsExplorer } from "@/components/dashboard/findings";
import { CompetitorPanel, PagesTable, PerformancePanel } from "@/components/dashboard/panels";

const STAGES = [
  ["crawl", "Crawling site"],
  ["competitors", "Benchmarking competitors"],
  ["performance", "Collecting performance data"],
  ["analysis", "Running audits"],
  ["ai", "Writing recommendations"],
  ["saving", "Saving"],
];

export default function AuditView({ id }: { id: string }) {
  const [audit, setAudit] = useState<Audit | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [actions, setActions] = useState<Record<string, Action>>({});
  const [tab, setTab] = useState("overview");
  const [category, setCategory] = useState("all");

  const loadFull = useCallback(async () => {
    const [a, acts] = await Promise.all([api.getAudit(id), api.getActions(id)]);
    setAudit(a);
    setActions(Object.fromEntries(acts.map((x) => [x.finding_id, x])));
  }, [id]);

  useEffect(() => {
    let stop = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const s = await api.getStatus(id);
        if (stop) return;
        if (s.status === "completed") return loadFull();
        setAudit((prev) => ({ ...(prev ?? { result: null }), ...s }));
        if (s.status !== "failed") timer = setTimeout(poll, 1500);
      } catch (e) {
        setError(e instanceof AccessCodeError ? "This dashboard needs an access code. Enter it on the home page, then reopen this audit." : (e as Error).message);
      }
    };
    poll();
    return () => {
      stop = true;
      clearTimeout(timer);
    };
  }, [id, loadFull]);

  async function setStatus(findingId: string, status: ActionStatus) {
    const a = actions[findingId];
    if (!a) return;
    setActions((prev) => ({ ...prev, [findingId]: { ...a, status } }));
    try {
      const updated = await api.updateAction(id, a.id, { status });
      setActions((prev) => ({ ...prev, [findingId]: updated }));
    } catch {
      setActions((prev) => ({ ...prev, [findingId]: a }));
    }
  }

  if (error) return <p className="text-critical">{error}</p>;
  if (!audit) return <Loader2 className="mx-auto mt-20 h-6 w-6 animate-spin text-muted-foreground" />;

  if (audit.status === "failed") {
    return (
      <Card className="mx-auto mt-10 max-w-xl">
        <CardContent className="space-y-3 pt-6 text-center">
          <AlertTriangle className="mx-auto h-8 w-8 text-critical" />
          <h2 className="font-semibold">Audit failed</h2>
          <p className="text-sm text-muted-foreground">{audit.error}</p>
          <Button asChild variant="outline">
            <Link href="/">
              <RefreshCw className="h-4 w-4" /> Try again
            </Link>
          </Button>
        </CardContent>
      </Card>
    );
  }

  if (audit.status !== "completed" || !audit.result) {
    const current = STAGES.findIndex(([k]) => k === audit.stage);
    return (
      <Card className="mx-auto mt-10 max-w-xl">
        <CardContent className="space-y-5 pt-6">
          <div>
            <div className="text-sm text-muted-foreground">Auditing</div>
            <div className="truncate font-semibold">{audit.url}</div>
          </div>
          <Progress value={Math.round(audit.progress * 100)} />
          <ol className="space-y-2 text-sm">
            {STAGES.map(([k, label], i) => (
              <li key={k} className={i < current ? "text-good" : i === current ? "font-medium" : "text-muted-foreground"}>
                {i < current ? "✓" : i === current ? <Loader2 className="mr-1 inline h-3.5 w-3.5 animate-spin" /> : "○"} {label}
              </li>
            ))}
          </ol>
          <p className="truncate text-xs text-muted-foreground">{audit.message}</p>
        </CardContent>
      </Card>
    );
  }

  const r = audit.result;
  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-6 lg:flex-row lg:items-center">
        <ScoreRing score={r.summary.overall_score} grade={r.summary.grade} />
        <div className="min-w-0 flex-1 space-y-2">
          <div className="text-sm text-muted-foreground">SEO audit · {audit.completed_at && new Date(audit.completed_at).toLocaleString()}</div>
          <h1 className="truncate text-2xl font-bold">{r.summary.url}</h1>
          <div className="flex flex-wrap gap-2 text-sm">
            {(["critical", "quick_win", "strategic", "long_term"] as const).map((b) => (
              <button key={b} onClick={() => setTab("plan")} className="rounded-md border bg-card px-2.5 py-1 hover:bg-muted">
                {r.buckets[b].label}: <b>{r.buckets[b].count}</b>
              </button>
            ))}
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" size="sm" asChild>
            <a href={api.exportUrl(id, "html")} target="_blank" rel="noreferrer">
              <FileText className="h-4 w-4" /> Report (print to PDF)
            </a>
          </Button>
          <Button variant="outline" size="sm" asChild>
            <a href={api.exportUrl(id, "csv")}>
              <Download className="h-4 w-4" /> Actions CSV
            </a>
          </Button>
          <Button variant="outline" size="sm" asChild>
            <a href={api.exportUrl(id, "json")}>
              <Download className="h-4 w-4" /> JSON
            </a>
          </Button>
        </div>
      </div>

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="plan">Action plan</TabsTrigger>
          <TabsTrigger value="findings">All findings ({r.findings.length})</TabsTrigger>
          <TabsTrigger value="pages">Pages</TabsTrigger>
          <TabsTrigger value="performance">Performance</TabsTrigger>
          <TabsTrigger value="competitors">Competitors</TabsTrigger>
        </TabsList>

        <TabsContent value="overview" className="space-y-4">
          <CategoryGrid
            result={r}
            onSelect={(c) => {
              setCategory(c);
              setTab("findings");
            }}
          />
          <div className="grid gap-4 lg:grid-cols-3">
            <div className="lg:col-span-2">
              <SummaryCard result={r} />
            </div>
            <SiteFacts result={r} />
          </div>
        </TabsContent>
        <TabsContent value="plan">
          <ActionPlan result={r} actions={actions} onStatus={setStatus} />
        </TabsContent>
        <TabsContent value="findings">
          <FindingsExplorer result={r} actions={actions} onStatus={setStatus} category={category} setCategory={setCategory} />
        </TabsContent>
        <TabsContent value="pages">
          <PagesTable auditId={id} />
        </TabsContent>
        <TabsContent value="performance">
          <PerformancePanel result={r} />
        </TabsContent>
        <TabsContent value="competitors">
          <CompetitorPanel result={r} />
        </TabsContent>
      </Tabs>
    </div>
  );
}
