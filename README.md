# SEO Audit Agent

AI-powered website SEO auditor. Submit a URL → it crawls the site, runs 8 specialist audit agents, scores the site and returns a prioritised, consultant-style action plan. Exports to PDF, HTML, CSV and JSON.

```
backend/   FastAPI + async crawler + audit agents + Claude advisor   (Python 3.11+)
frontend/  Next.js 15 dashboard                                      (Node 20+)
docs/      ARCHITECTURE.md — pipeline, decisions, security, scoring
```

## What it checks

| Agent | Checks |
|---|---|
| **A. Technical** | HTTPS + redirect, www/non-www, robots.txt, XML sitemaps (incl. indexes, dirty URLs), 4xx/5xx, redirect chains, noindex, canonicals, viewport, `lang`, mixed content, HSTS, hreflang |
| **B. On-page** | Title / meta description missing, length, duplicates · H1 & heading hierarchy · image alt & dimensions · Open Graph / Twitter · URL hygiene |
| **C. Content** | Thin & duplicate content · author/date (E-E-A-T) · readability · missing editorial/blog strategy |
| **D. Internal links** | Orphans, weak inbound links, click depth, dead ends, generic/empty anchors, internal nofollow, links to broken URLs |
| **E. Performance** | Server response time, HTML weight, render-blocking scripts, script count, compression, lazy-loading, image formats, caching · optional Lighthouse lab data (LCP, CLS, TBT) via PageSpeed Insights |
| **F. Structured data** | JSON-LD parse errors, required/recommended props (Product, Offer, Article, Organization, FAQ, Recipe…), missing Product/Organization/Breadcrumb schema |
| **G. AI-search readiness** | AI search bots blocked in robots.txt (OAI-SearchBot, Claude-SearchBot, PerplexityBot…), JS-only content, answer-style structure, brand entity (`sameAs`), About page, freshness, llms.txt |
| **H. Competitors** | Up to 3 competitors crawled shallowly: content depth, schema gaps, blog/FAQ gaps, speed gap |

The **AI layer** (Claude, `claude-opus-5-5`) turns the findings into an executive summary, top priorities, quick wins, content ideas, AI-search actions and a 30/60/90-day roadmap. It only interprets measured findings. Without an API key it falls back to a rule-based summary, so the tool runs with no AI cost.

## Quick start (local)

```bash
# Backend
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
cp ../.env.example .env            # optional: add ANTHROPIC_API_KEY, SEO_PAGESPEED_API_KEY
.venv/bin/uvicorn app.main:app --reload --port 8000
.venv/bin/pytest                   # 36 tests, no network needed

# Frontend (new terminal)
cd frontend
npm install
npm run dev                        # http://localhost:3000
```

## Deploy on Vercel

Two Vercel projects from this repo (`backend` + `frontend`), about 20 minutes, free tier works. Step-by-step: **[docs/DEPLOY_VERCEL.md](docs/DEPLOY_VERCEL.md)**.

## Docker

```bash
cp .env.example .env               # fill in keys
docker compose up --build          # web :3000, api :8000
```
The dashboard calls the backend through its own `/api` proxy (`BACKEND_URL`, `BACKEND_API_KEY`, optional `APP_ACCESS_CODE`).

## API

| Method | Path | Notes |
|---|---|---|
| `POST` | `/api/audits` | `{"url", "max_pages"?, "max_depth"?, "competitors"?: [≤3], "respect_robots"?: true, "use_ai"?: true}` → `202 {"id"}` |
| `GET` | `/api/audits` | Recent audits |
| `GET` | `/api/audits/{id}` | Full result (scores, issues, pages, AI insights) |
| `GET` | `/api/audits/{id}/status` | Lightweight progress poll |
| `GET` | `/api/audits/{id}/report.{pdf\|html\|json\|csv}` | CSV: `?kind=issues` (default) or `?kind=pages` |
| `DELETE` | `/api/audits/{id}` | |
| `GET` | `/api/health` | |
| `POST` | `/api/audit/run` | **Stateless** (used by the dashboard / Vercel): crawl + score in one request, returns the full result |
| `POST` | `/api/insights` | Body: an audit result → Claude recommendations |
| `POST` | `/api/report.{pdf\|html\|json\|csv}` | Body: an audit result → file |

Interactive docs: `http://localhost:8000/docs`.

## Running costs

| Item | Cost |
|---|---|
| Hosting | Runs on a ₹500–1,500/month VPS (1–2 vCPU, 2 GB RAM) |
| Claude | One call per audit, roughly 10–20K input tokens plus 3–8K output tokens (thinking included). That's about $0.10–0.25 per audit on Opus 5.5 at `medium` effort ($4/$20 per M tokens). Set `SEO_AI_MODEL=claude-sonnet-5-5` to roughly halve it |
| PageSpeed Insights | Free (API key from Google Cloud console) |

## Known limits

- **No JavaScript rendering**: content injected client-side is not seen. This is flagged as an issue, since most AI crawlers don't render JS either.
- **No ranking or keyword data**: that needs Search Console or a paid SERP API (on the roadmap).
- **Single instance**: jobs run in-process, so a restart drops running audits. See `docs/ARCHITECTURE.md` §5 for the scaling path.
- **DNS rebinding**: run behind an egress firewall in production. See `docs/ARCHITECTURE.md` §3.
