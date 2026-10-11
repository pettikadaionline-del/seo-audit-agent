"use client";

import { Suspense } from "react";
import { useSearchParams } from "next/navigation";
import AuditView from "./AuditView";

// Query-string route (/audit?id=…) so the dashboard can be a fully static export served by the API.
function AuditRoute() {
  const id = useSearchParams().get("id");
  if (!id) return <p className="text-muted-foreground">No audit selected.</p>;
  return <AuditView key={id} id={id} />;
}

export default function Page() {
  return (
    <Suspense fallback={null}>
      <AuditRoute />
    </Suspense>
  );
}
