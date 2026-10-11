# SEO Audit Agent

Enter a URL and get a live crawl, 8 audit categories, a weighted 0–100 score, and a prioritised action plan. Every finding comes with evidence (affected URLs plus the values that were observed). Claude adds explanations and fix steps on top of these findings. It never creates findings.

```
Browser ─► Next.js (dashboard + /api proxy) ─► FastAPI
                                               ├─ Crawler: robots.txt, sitemaps, BFS crawl, SSRF guard, rate limiting
                                               ├─ PageSpeed Insights: CrUX field data + Lighthouse lab (kept separate)
                                               ├─ 8 audit modules → deterministic findings
                                               ├─ Scoring + prioritisation (transparent formula)
                                               ├─ Claude: summary, fix steps, code examples (schema-validated JSON)
                                               └─ PostgreSQL / SQLite: audits, pages, action tracking
```

## Quick start

### Deploy (one click, free tier)
[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/pettikadaionline-del/seo-audit-agent)

You'll be asked for three values:

| Variable | What to enter |
|---|---|
| `ACCESS_CODE` | Any password you choose. Visitors need it to run audits, so strangers can't use your Claude credits |
| `ANTHROPIC_API_KEY` | Optional. Without it, recommendations are rule-based |
| `PAGESPEED_API_KEY` | Optional. A free Google key that raises the quota for Core Web Vitals data |

Your link will be `https://seo-audit-agent-xxxx.onrender.com`. On the free plan:
- The service sleeps after 15 minutes idle, so the first visit afterwards takes about 1 minute.
- Audit history is cleared on restart, so export reports you want to keep.
- For persistent history, add a Render Postgres database and set `DATABASE_URL` to its URL; `postgres://` URLs are handled automatically.

### Docker (any VPS)
```bash
cp .env.example .env        # set ACCESS_CODE, optionally ANTHROPIC_API_KEY
docker compose up --build   # dashboard + API on http://localhost:8000, Postgres for history
```

### Local dev
```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r backend/requirements-dev.txt
cd backend && uvicorn app.main:app --reload          # API on :8000 (SQLite)

cd frontend && npm install && npm run dev             # dashboard on :3000, proxies /api to :8000
```
In production the dashboard is a static export (`npm run build` → `out/`), served by FastAPI on the same origin as the API (see `Dockerfile`).

### Tests
```bash
cd backend && pytest -q
```
There are 38 tests: SSRF blocking (including DNS-rebinding defence), HTML parsing, each audit module, scoring, the AI layer (mocked Claude client, covering refusal and invalid-output fallbacks), PageSpeed field-vs-lab parsing, the access-code gate, and an end-to-end API run. The end-to-end test does a real HTTP crawl of `tests/fixture_site`, a small site with known planted issues, and checks that each planted issue is found.

## What gets audited

| Category | Weight | Checks (examples) |
|---|---|---|
| Technical | 20% | HTTPS + redirect, HSTS, robots.txt, sitemap validity & contents, 5xx, redirect chains, noindex, canonicals, exact duplicates, viewport, lang, mixed content, URL hygiene, hreflang |
| On-page | 15% | Title/description missing, length, duplicates; H1; heading hierarchy; image alt; Open Graph |
| Content | 15% | Thin pages, near-duplicates (shingle similarity), readability, unstructured long pages, JS-only content |
| Links | 10% | Broken internal/external links, redirecting links, nofollow internal, generic anchors, orphan pages, click depth, dead ends |
| Performance | 15% | Crawler: TTFB, HTML weight, compression, render-blocking scripts, image dimensions, lazy-loading. PSI: real-user LCP/INP/CLS (CrUX) and Lighthouse lab results, labelled separately |
| Structured data | 8% | JSON-LD syntax, required properties per type (Product/Offer, Article, Organization, Breadcrumb, FAQ…), Organization on homepage |
| AI search readiness | 10% | AI search vs training bot access in robots.txt, llms.txt (flagged as unofficial), extractable text, Q&A content, author/date signals, trust pages, `sameAs` entity links |
| Competitors | 7% | Light crawl of up to 3 competitors: content depth, schema gaps, FAQ gap, TTFB, meta coverage, site size. No ranking, traffic or backlink claims |

The competitor weight is only used when competitors are provided. Otherwise the remaining weights are re-normalised.

## Scoring & prioritisation (`backend/app/audits/scoring.py`)
- **Category score** = 100 − Σ(severity points × reach). Severity points: critical 30, high 15, medium 7, low 3, info 0. Reach = 1.0 for site-wide findings, otherwise 0.4 + 0.6 × (share of pages affected).
- **Overall score** = weighted mean of category scores. Grades: A ≥ 90, B ≥ 75, C ≥ 60, D ≥ 40, F below 40.
- **Impact** (1–5) comes from severity. Medium/high findings that affect at least 50% of pages get +1. **Effort** (1–5) is set per check.
- **Buckets:** critical severity → Critical Fixes. Impact ≥ 3 and effort ≤ 2 → Quick Wins. Impact ≥ 3 → Strategic. Everything else → Long-Term.

## AI layer (`backend/app/ai/recommender.py`)
- Uses the Anthropic SDK with `claude-opus-5-5`, adaptive thinking, `effort: medium`, and a structured-output JSON schema validated with Pydantic.
- Server-side refusal fallback is enabled (`fallbacks: "default"`).
- Crawled text is wrapped in `<site_data>` and treated as untrusted (defence against prompt injection). Advice for finding IDs that don't exist in the audit is dropped.
- If there is no key, or the API errors, refuses or returns invalid output, the audit still completes with rule-based recommendations. The UI shows "Rule-based" vs "AI-generated".
- Cost: one call per audit, covering up to 40 findings. At Opus 5.5 pricing ($4/$20 per M tokens) that's roughly **$0.10–0.40 per audit**. Set `AI_EFFORT=low` to cut that further.

## Safety & crawler etiquette
- **Access code:** with `ACCESS_CODE` set, every API call except `/api/health` requires it (constant-time compare).
- **SSRF:** only http/https on ports 80/443/8080/8443. Every URL and every redirect hop is DNS-resolved and rejected if it points to a private, loopback, link-local, CGNAT or metadata address. The IP actually connected to is re-checked after connecting (DNS rebinding). `ALLOW_PRIVATE_TARGETS=true` is for local testing only.
- **Politeness:** robots.txt is respected, including `Crawl-delay` (capped at 10s). Requests to each host are throttled (default 0.5s), and concurrency, page count, depth and response size (5 MB) are all capped. Sitemap gzip-bombs and XXE are blocked.
- **Evidence over opinion:** heuristic checks are marked `confidence: medium`. The AI never claims guaranteed rankings, rich results or AI citations.

## Exports & action tracking
- Every finding becomes an action with a status (To do / In progress / Done / Won't fix), an owner and notes.
- Exports:
  - **HTML report** (print to PDF)
  - **CSV action plan**, including status and owner (opens straight into Sheets/Excel)
  - **Full JSON**

## Known limitations / scale-up path
- **Job runner:** audits run in-process (asyncio, capped by `MAX_CONCURRENT_AUDITS`). That's fine for one server. For multiple API instances, move `execute_audit()` onto a Redis-backed queue (arq or Celery); the function is already self-contained. Redis was left out deliberately until that's needed.
- **No JavaScript rendering:** the crawler reads raw HTML, which is also what most AI crawlers see. JS-only content is flagged rather than rendered. A Playwright rendering pass is the next upgrade for SPA-heavy sites.
- **Field data:** CrUX field data only exists for sites with enough Chrome traffic. Without a `PAGESPEED_API_KEY`, anonymous PSI quota is low.
- **Database:** the schema is created on startup. Add Alembic before changing models in production.
