"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, getAccessCode, setAccessCode, type AuditListItem } from "@/lib/api";
import { deleteAudit, listAudits, saveAudit } from "@/lib/storage";

type Stage = "idle" | "crawl" | "ai" | "done";

const withScheme = (u: string) => (/^https?:\/\//i.test(u) ? u : `https://${u}`);

export default function Home() {
  const router = useRouter();
  const [url, setUrl] = useState("");
  const [maxPages, setMaxPages] = useState(25);
  const [competitors, setCompetitors] = useState("");
  const [useAi, setUseAi] = useState(true);
  const [code, setCode] = useState("");
  const [stage, setStage] = useState<Stage>("idle");
  const [elapsed, setElapsed] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [recent, setRecent] = useState<AuditListItem[]>([]);

  useEffect(() => {
    setRecent(listAudits());
    setCode(getAccessCode());
  }, []);

  useEffect(() => {
    if (stage === "idle" || stage === "done") return;
    const t = setInterval(() => setElapsed((s) => s + 1), 1000);
    return () => clearInterval(t);
  }, [stage]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setNotice(null);
    setElapsed(0);
    setAccessCode(code);
    const comps = competitors.split(/[\s,]+/).filter(Boolean).map(withScheme).slice(0, 3);
    try {
      setStage("crawl");
      const audit = await api.run({ url: withScheme(url.trim()), max_pages: maxPages, competitors: comps });
      saveAudit(audit);
      if (useAi) {
        setStage("ai");
        setElapsed(0);
        try {
          audit.ai = await api.insights(audit);
          saveAudit(audit);
        } catch (err) {
          // The audit itself succeeded; AI is a bonus layer.
          setNotice(`Audit saved, but AI recommendations failed: ${err instanceof Error ? err.message : err}`);
        }
      }
      setStage("done");
      router.push(`/audits/${audit.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setStage("idle");
    }
  }

  const busy = stage === "crawl" || stage === "ai";

  return (
    <>
      <section className="panel">
        <h1>Audit a website</h1>
        <p className="muted">
          Crawls the site, runs 8 specialist audit agents and turns the findings into a prioritised action plan.
        </p>
        <form onSubmit={submit}>
          <div className="row">
            <div className="field grow">
              <label htmlFor="url">Website URL</label>
              <input id="url" type="text" placeholder="https://www.example.com" value={url} onChange={(e) => setUrl(e.target.value)} required disabled={busy} />
            </div>
            <div className="field" style={{ width: 120 }}>
              <label htmlFor="pages">Max pages</label>
              <input id="pages" type="number" min={1} max={30} value={maxPages} onChange={(e) => setMaxPages(Number(e.target.value))} disabled={busy} />
            </div>
          </div>
          <div className="row" style={{ marginTop: 12 }}>
            <div className="field grow">
              <label htmlFor="comp">Competitors (optional, up to 3, comma separated)</label>
              <input id="comp" type="text" placeholder="competitor1.com, competitor2.com" value={competitors} onChange={(e) => setCompetitors(e.target.value)} disabled={busy} />
            </div>
            <div className="field" style={{ width: 160 }}>
              <label htmlFor="code">Access code</label>
              <input id="code" type="password" autoComplete="off" value={code} onChange={(e) => setCode(e.target.value)} disabled={busy} />
            </div>
          </div>
          <div className="row" style={{ marginTop: 12, justifyContent: "space-between" }}>
            <label style={{ display: "flex", gap: 6, alignItems: "center" }}>
              <input type="checkbox" checked={useAi} onChange={(e) => setUseAi(e.target.checked)} disabled={busy} /> AI recommendations (Claude)
            </label>
            <button className="btn primary" disabled={busy || !url}>
              {busy ? "Working…" : "Run audit"}
            </button>
          </div>
        </form>
        {busy && (
          <div style={{ marginTop: 16 }}>
            <p style={{ margin: "0 0 6px" }}>
              {stage === "crawl" ? "Step 1/2 · Crawling and analysing the site (up to ~45 s)" : "Step 2/2 · Writing AI recommendations (up to ~40 s)"}
              <span className="muted"> · {elapsed}s</span>
            </p>
            <div className="progress"><span style={{ width: `${stage === "crawl" ? Math.min(60, elapsed * 1.4) : 60 + Math.min(38, elapsed)}%` }} /></div>
          </div>
        )}
        {error && <p className="error">{error}</p>}
        {notice && <p className="error">{notice}</p>}
      </section>

      <section className="panel">
        <h2>Recent audits <span className="muted" style={{ fontWeight: 400, fontSize: 13 }}>(saved in this browser)</span></h2>
        {recent.length === 0 ? (
          <p className="muted">No audits yet.</p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th>Site</th><th>Score</th><th>Date</th><th /></tr>
              </thead>
              <tbody>
                {recent.map((a) => (
                  <tr key={a.id}>
                    <td className="url"><Link href={`/audits/${a.id}`}>{a.url}</Link></td>
                    <td>{a.overall_score != null ? `${a.overall_score} (${a.grade})` : "–"}</td>
                    <td className="muted">{new Date(a.created_at).toLocaleString()}</td>
                    <td>
                      <button className="btn" style={{ padding: "2px 10px" }} onClick={() => { deleteAudit(a.id); setRecent(listAudits()); }}>
                        Delete
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </>
  );
}
