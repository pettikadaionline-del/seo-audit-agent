"use client";

import { AlertOctagon, Compass, Hourglass, Zap } from "lucide-react";
import type { Action, ActionStatus, AuditResult, Bucket } from "@/lib/api";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { FindingRow } from "./findings";

const BUCKETS: { key: Bucket; icon: React.ElementType; blurb: string; tone: string }[] = [
  { key: "critical", icon: AlertOctagon, blurb: "Blocking issues. Fix before anything else.", tone: "text-critical" },
  { key: "quick_win", icon: Zap, blurb: "High impact, low effort. Usually under a day each.", tone: "text-good" },
  { key: "strategic", icon: Compass, blurb: "High impact, needs planning or development time.", tone: "text-primary" },
  { key: "long_term", icon: Hourglass, blurb: "Smaller gains. Batch into routine maintenance.", tone: "text-muted-foreground" },
];

export function ActionPlan({
  result,
  actions,
  onStatus,
}: {
  result: AuditResult;
  actions: Record<string, Action>;
  onStatus: (findingId: string, s: ActionStatus) => void;
}) {
  const all = Object.values(actions);
  const done = all.filter((a) => a.status === "done" || a.status === "wont_fix").length;
  return (
    <div className="space-y-4">
      <Card>
        <CardContent className="flex flex-wrap items-center gap-4 pt-5">
          <div className="text-sm font-medium">
            Progress: {done} of {all.length} actions closed
          </div>
          <Progress value={all.length ? (done / all.length) * 100 : 0} className="max-w-md flex-1" />
          <div className="text-xs text-muted-foreground">Ordered by priority score (impact × 2 − effort) within each group.</div>
        </CardContent>
      </Card>
      {BUCKETS.map(({ key, icon: Icon, blurb, tone }) => {
        const fs = result.findings.filter((f) => f.priority.bucket === key);
        if (!fs.length) return null;
        return (
          <Card key={key}>
            <CardHeader>
              <div className="flex items-center gap-2">
                <Icon className={`h-5 w-5 ${tone}`} />
                <CardTitle>
                  {result.buckets[key].label} <span className="text-muted-foreground">({fs.length})</span>
                </CardTitle>
              </div>
              <CardDescription>{blurb}</CardDescription>
            </CardHeader>
            <CardContent>
              {fs.map((f) => (
                <FindingRow key={f.id} f={f} advice={result.ai.findings[f.id]} action={actions[f.id]} onStatus={(s) => onStatus(f.id, s)} />
              ))}
            </CardContent>
          </Card>
        );
      })}
    </div>
  );
}
