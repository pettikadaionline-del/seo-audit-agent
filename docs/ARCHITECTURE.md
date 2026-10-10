# Architecture

## 1. Pipeline

```
 POST /api/audits ──► SSRF check ──► AuditRunner (asyncio task)
                                        │
   ┌────────────────────────────────────┘
   ▼
 1. Site checks     robots.txt · sitemaps (index + gzip) · http→https · www/non-www · llms.txt
 2. Crawl           BFS, same-site, robots-aware, concurrency + delay, depth & page caps
 3. Parse           BeautifulSoup/lxml → PageData (meta, headings, links, images, JSON-LD, resources)
 4. PageSpeed       optional, Google PSI API (homepage, mobile) — runs in parallel with crawl
 5. Competitors     optional, ≤3 sites × 15 pages, profiled (not ranked)
 6. Agents A–H      deterministic rules → Issue[] with evidence + affected URLs
 7. Scoring         category scores, overall score, grade, priority per issue
 8. AI layer        Claude turns findings into summary, priorities, roadmap (fallback: heuristic)
 9. Persist         SQLite (JSON blob per audit) → API → dashboard / PDF / CSV / HTML / JSON
```

## 2. Key decisions

| Decision | Choice | Why | Trade-off |
|---|---|---|---|
| Facts vs. advice | Rule agents find issues; LLM only interprets | Reproducible, testable, no hallucinated issues | LLM can't spot issues the rules don't cover |
| AI provider | Claude via official `anthropic` SDK, structured output (`messages.parse` + Pydantic) | Typed JSON, no parsing hacks; server-side refusal fallback on | API cost per audit (~1 call, ~10–20K input tokens) |
| AI optional | Heuristic summary when no key / API error | Product works at ₹0 AI spend; AI never fails an audit | Heuristic text is generic |
| Crawler | `httpx` async, raw HTML (no JS rendering) | Fast, cheap, mirrors what most AI crawlers see | JS-only sites look thin (flagged by `ai_readiness.js_rendering`) |
| Performance | Crawl signals + optional PageSpeed Insights API | Free, real Lighthouse data without running Chrome | PSI quota; homepage only |
| Jobs | In-process asyncio tasks | Zero infra | Jobs lost on restart; single instance (see §5) |
| Storage | SQLite, one JSON row per audit | Zero-ops, portable | Not for multi-instance; swap for Postgres |
| Frontend | Next.js 15 (App Router) client components, plain CSS | No UI lib lock-in, small bundle (~108 KB) | Hand-rolled components |

## 3. Security

| Threat | Control | Where |
|---|---|---|
| SSRF to internal services / cloud metadata | Scheme allow-list (http/https), port allow-list (80/443/8080/8443), blocked hostnames (`localhost`, `*.internal`, `*.local`, metadata), single-label hosts rejected, DNS resolved and **every** IP checked (private, loopback, link-local, CGNAT, reserved, IPv4-mapped IPv6) | `app/security/url_guard.py` |
| Redirect to internal host | Redirects followed manually; every hop re-validated | `app/crawler/fetcher.py` |
| Resource exhaustion | Page cap (≤500), depth cap (≤6), response size cap (5 MB), timeouts, max 5 redirects, concurrency limit, competitor cap | `config.py`, crawler |
| Abuse of the API | Per-IP rate limit on audit creation; optional `X-API-Key` | `app/main.py` |
| Being a bad crawler | robots.txt honoured by default (incl. `Crawl-delay`), identifiable User-Agent, delay between requests | crawler |
| Prompt injection via crawled pages | Only compact, structured findings + titles go to Claude; system prompt forbids inventing facts; output is schema-constrained | `app/ai/advisor.py` |
| Secret leakage | PageSpeed key stripped from error messages; keys only via env | `integrations/pagespeed.py` |
| XSS in reports | All page-derived text HTML-escaped in HTML/PDF exports; React escapes by default | `reports/exporters.py` |

**Residual risk — DNS rebinding:** the URL is resolved for validation and again by `httpx` when connecting. A hostile DNS server could answer differently the second time. Fixes, in order of effort: run the API in a network namespace / egress proxy that blocks RFC1918 + metadata IPs (recommended for production), or pin the resolved IP in a custom transport.

## 4. Scoring model

- **Category score** = 100 − Σ penalty, penalty = severity points × (0.4 + 0.6 × share of pages affected).
  Severity points: critical 30, high 15, medium 7, low 3, info 0.
- **Overall** = weighted mean: technical 22%, on-page 18%, content 16%, performance 12%, links 10%, structured data 10%, AI readiness 8%, competitor 4% (only when competitors are supplied).
- **Grade**: A ≥ 90, B ≥ 80, C ≥ 65, D ≥ 50, F < 50.
- **Priority** = impact (1–10) × severity multiplier × reach ÷ effort cost × 10 — sorts the Action Center.

All constants live in `app/scoring.py`; tune them there.

## 5. Scaling path

| Stage | Volume | Change |
|---|---|---|
| Now | 1 instance, ~tens of audits/day | As built |
| Next | Hundreds/day, multiple instances | Move jobs to a queue (RQ/Celery/Arq + Redis), Postgres for storage, put the API behind an egress proxy for SSRF hardening |
| Later | SaaS | Auth + per-user quotas, scheduled re-audits with diff ("what changed since last audit"), Search Console API for real impressions/clicks, optional Playwright rendering for JS sites |

## 6. Adding a rule

1. Pick the agent in `app/agents/`.
2. Emit `self.issue("rule.id", Severity.x, title, description, recommendation, urls, impact=, effort=, **evidence)`.
3. Add a case to the fake site in `tests/conftest.py` and assert it in `tests/test_audit_pipeline.py`.
