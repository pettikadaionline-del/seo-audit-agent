"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, type AuditListItem } from "@/lib/api";

export default function Home() {
  const router = useRouter();
  const [url, setUrl] = useState("");
  const [maxPages, setMaxPages] = useState(50);
  const [competitors, setCompetitors] = useState("");
  const [useAi, setUseAi] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [recent, setRecent] = useState<AuditListItem[]>([]);

  useEffect(() => {
    api.list().then(setRecent).catch(() => setRecent([]));
  }, []);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    let target = url.trim();
    if (target && !/^https?:\/\//i.test(target)) target = `https://${target}`;
    try {
      const comps = competitors
        .split(/[\s,]+/)
        .map((c) => c.trim())
        .filter(Boolean)
        .map((c) => (/^https?:\/\//i.test(c) ? c : `https://${c}`))
        .slice(0, 3);
      const { id } = await api.create({ url: target, max_pages: maxPages, competitors: comps, use_ai: useAi });
      router.push(`/audits/${id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setBusy(false);
    }
  }

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
              <input id="url" type="text" placeholder="https://www.example.com" value={url} onChange={(e) => setUrl(e.target.value)} required />
            </div>
            <div className="field" style={{ width: 130 }}>
              <label htmlFor="pages">Max pages</label>
              <input id="pages" type="number" min={1} max={500} value={maxPages} onChange={(e) => setMaxPages(Number(e.target.value))} />
            </div>
          </div>
          <div className="row" style={{ marginTop: 12 }}>
            <div className="field grow">
              <label htmlFor="comp">Competitors (optional, up to 3, comma separated)</label>
              <input id="comp" type="text" placeholder="competitor1.com, competitor2.com" value={competitors} onChange={(e) => setCompetitors(e.target.value)} />
            </div>
            <label style={{ display: "flex", gap: 6, alignItems: "center", paddingBottom: 10 }}>
              <input type="checkbox" checked={useAi} onChange={(e) => setUseAi(e.target.checked)} /> AI recommendations
            </label>
            <button className="btn primary" disabled={busy || !url}>
              {busy ? "Starting…" : "Run audit"}
            </button>
          </div>
          {error && <p className="error">{error}</p>}
        </form>
      </section>

      <section className="panel">
        <h2>Recent audits</h2>
        {recent.length === 0 ? (
          <p className="muted">No audits yet.</p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th>Site</th><th>Status</th><th>Score</th><th>Date</th></tr>
              </thead>
              <tbody>
                {recent.map((a) => (
                  <tr key={a.id}>
                    <td className="url"><Link href={`/audits/${a.id}`}>{a.url}</Link></td>
                    <td>{a.status}</td>
                    <td>{a.overall_score != null ? `${a.overall_score} (${a.grade})` : "–"}</td>
                    <td className="muted">{new Date(a.created_at).toLocaleString()}</td>
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
