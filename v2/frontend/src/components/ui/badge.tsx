import * as React from "react";
import { cn } from "@/lib/utils";

const SEVERITY: Record<string, string> = {
  critical: "bg-critical/15 text-critical",
  high: "bg-high/15 text-high",
  medium: "bg-medium/15 text-medium",
  low: "bg-low/15 text-low",
  info: "bg-info/15 text-info",
};

export function Badge({ className, ...props }: React.HTMLAttributes<HTMLSpanElement>) {
  return <span className={cn("inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium", className)} {...props} />;
}

export function SeverityBadge({ severity }: { severity: string }) {
  return <Badge className={cn("uppercase tracking-wide", SEVERITY[severity])}>{severity}</Badge>;
}
