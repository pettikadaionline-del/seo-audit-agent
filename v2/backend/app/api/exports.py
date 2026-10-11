"""Report exports: JSON (full data), CSV (action plan) and a self-contained,
printable HTML report (use the browser's Print → Save as PDF)."""

import csv
import io
from html import escape

from app.audits.scoring import BUCKET_LABELS

SEV_COLORS = {"critical": "#b91c1c", "high": "#c2410c", "medium": "#a16207", "low": "#1d4ed8", "info": "#475569"}


def to_csv(audit, actions: dict) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "bucket", "severity", "category", "title", "impact", "effort", "affected_count", "status", "owner", "recommendation", "affected_urls"])
    ai = (audit.result or {}).get("ai", {}).get("findings", {})
    for f in (audit.result or {}).get("findings", []):
        a = actions.get(f["id"])
        steps = ai.get(f["id"], {}).get("fix_steps") or [f["recommendation"]]
        w.writerow([
            f["id"], BUCKET_LABELS[f["priority"]["bucket"]], f["severity"], f["category"], f["title"],
            f["priority"]["impact"], f["priority"]["effort"], len(f["affected_urls"]),
            a.status if a else "todo", (a.owner or "") if a else "",
            " | ".join(steps), " ".join(f["affected_urls"][:50]),
        ])
    return buf.getvalue()


def to_html(audit, actions: dict) -> str:
    r = audit.result or {}
    s = r.get("summary", {})
    ai = r.get("ai", {})
    cats = r.get("categories", {})
    e = lambda x: escape(str(x if x is not None else ""))  # noqa: E731

    cat_rows = "".join(
        f"<tr><td>{e(c['label'])}</td><td><b>{c['score']}</b>/100</td><td>{round(c['weight'] * 100)}%</td><td>{c['findings']}</td></tr>"
        for c in cats.values()
    )
    sections = []
    for bucket, label in BUCKET_LABELS.items():
        fs = [f for f in r.get("findings", []) if f["priority"]["bucket"] == bucket]
        if not fs:
            continue
        cards = []
        for f in fs:
            adv = ai.get("findings", {}).get(f["id"], {})
            steps = "".join(f"<li>{e(x)}</li>" for x in (adv.get("fix_steps") or [f["recommendation"]]))
            code = f"<pre>{e(adv['code_example'])}</pre>" if adv.get("code_example") else ""
            urls = "".join(f"<li>{e(u)}</li>" for u in f["affected_urls"][:10])
            more = f"<li>… and {len(f['affected_urls']) - 10} more</li>" if len(f["affected_urls"]) > 10 else ""
            status = actions.get(f["id"]).status if actions.get(f["id"]) else "todo"
            cards.append(f"""
            <div class="card">
              <div class="row"><span class="sev" style="background:{SEV_COLORS[f['severity']]}">{e(f['severity'])}</span>
              <b>{e(f['id'])} · {e(f['title'])}</b><span class="muted">impact {f['priority']['impact']}/5 · effort {f['priority']['effort']}/5 · {e(status)}</span></div>
              <p>{e(adv.get('why_it_matters') or f['description'])}</p>
              {f"<p><i>{e(adv['business_impact'])}</i></p>" if adv.get('business_impact') else ''}
              <ol>{steps}</ol>{code}
              {f"<details><summary>{len(f['affected_urls'])} affected URL(s)</summary><ul>{urls}{more}</ul></details>" if f['affected_urls'] else ''}
            </div>""")
        sections.append(f"<h2>{e(label)} ({len(fs)})</h2>{''.join(cards)}")

    prios = "".join(f"<li>{e(p)}</li>" for p in ai.get("top_priorities", []))
    caveats = "".join(f"<li>{e(c)}</li>" for c in ai.get("caveats", []))
    opps = "".join(f"<li><b>{e(o['title'])}</b>: {e(o['rationale'])}</li>" for o in ai.get("content_opportunities", []))
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SEO Audit – {e(s.get('url'))}</title>
<style>
body{{font-family:system-ui,-apple-system,Segoe UI,sans-serif;max-width:960px;margin:2rem auto;padding:0 1rem;color:#0f172a;line-height:1.5}}
h1{{margin-bottom:0}} .muted{{color:#64748b;font-size:.85rem;margin-left:auto}} table{{border-collapse:collapse;width:100%}}
td,th{{border-bottom:1px solid #e2e8f0;padding:.4rem;text-align:left}} .score{{font-size:3rem;font-weight:700}}
.card{{border:1px solid #e2e8f0;border-radius:8px;padding:1rem;margin:.75rem 0;break-inside:avoid}} .row{{display:flex;gap:.5rem;align-items:center;flex-wrap:wrap}}
.sev{{color:#fff;border-radius:4px;padding:0 .4rem;font-size:.75rem;text-transform:uppercase}} pre{{background:#f1f5f9;padding:.75rem;overflow:auto;font-size:.8rem}}
@media print{{details{{display:block}} details>*{{display:block}}}}
</style></head><body>
<h1>SEO Audit Report</h1><p class="muted" style="margin-left:0">{e(s.get('url'))} · {e(audit.completed_at.strftime('%Y-%m-%d %H:%M UTC') if audit.completed_at else '')} · {s.get('pages_audited')} pages audited</p>
<div class="score">{s.get('overall_score')}/100 <span style="font-size:1.5rem">Grade {e(s.get('grade'))}</span></div>
<h2>Executive summary</h2><p>{e(ai.get('executive_summary'))}</p>
{f"<h3>Top priorities</h3><ol>{prios}</ol>" if prios else ''}
<h2>Category scores</h2><table><tr><th>Category</th><th>Score</th><th>Weight</th><th>Findings</th></tr>{cat_rows}</table>
{''.join(sections)}
{f"<h2>Content opportunities</h2><ul>{opps}</ul>" if opps else ''}
<h2>Method &amp; limitations</h2><ul>{caveats}
<li>Findings come from a live crawl of up to {s.get('pages_crawled')} URLs; pages beyond the crawl limit were not audited.</li>
<li>Crawler timings are measured from the audit server and are indicative only; Core Web Vitals use Chrome UX Report field data where Google provides it.</li>
<li>Structured data validity makes pages eligible for rich results; it does not guarantee them. No audit can guarantee rankings or AI citations.</li></ul>
<p class="muted" style="margin-left:0">Recommendations source: {e(ai.get('source'))}{(' · ' + e(ai.get('model'))) if ai.get('model') else ''}</p>
</body></html>"""
