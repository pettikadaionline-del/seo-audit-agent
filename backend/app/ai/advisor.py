"""AI orchestration layer: turns deterministic findings into a consultant-grade plan.

Claude only *interprets* findings that the rule-based agents produced (passed
in as compact JSON). It is told not to invent issues. If no API key is set or
the call fails, a deterministic heuristic summary is returned instead, so the
product works with zero AI spend.
"""
from __future__ import annotations

import json
import logging
import os

import anthropic
from pydantic import BaseModel, Field

from app.config import Settings
from app.models import AIInsights, AuditResult, Effort, Severity

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a senior technical SEO consultant writing the strategy section of a website audit.

You receive the audit's measured findings as JSON: scores, issues with severity, affected page counts and evidence,
and a sample of page titles. Every issue was detected by deterministic crawlers, so treat them as facts.

Write for a business owner who will hand the plan to a developer or marketer:
- Ground every statement in the supplied findings. Do not invent issues, metrics, rankings, traffic or keyword volumes.
- Prioritise by business impact versus effort. Name the specific pages or page templates when evidence allows.
- Infer the site's niche and audience from titles and content samples, and tailor content and AI-search advice to it.
- Keep each list item to one or two sentences, starting with the action.
"""


class _AIOutput(BaseModel):
    executive_summary: str = Field(description="4-6 sentence plain-English summary of site health and the biggest levers")
    top_priorities: list[str] = Field(description="5-7 highest-impact actions, ordered")
    quick_wins: list[str] = Field(description="3-6 changes doable in under a day")
    content_opportunities: list[str] = Field(description="3-6 content ideas tailored to the site's niche")
    ai_search_recommendations: list[str] = Field(description="3-5 actions to get cited in AI answer engines")
    days_30: list[str]
    days_60: list[str]
    days_90: list[str]


def _compact_findings(result: AuditResult, limit: int) -> dict:
    return {
        "site": result.url,
        "overall_score": result.overall_score,
        "category_scores": {c.category.value: c.score for c in result.category_scores},
        "pages_crawled": result.stats.get("pages_crawled"),
        "page_titles_sample": [p.title for p in result.pages[:15] if p.title],
        "issues": [
            {
                "id": i.id,
                "severity": i.severity.value,
                "title": i.title,
                "affected_pages": i.evidence.get("total_affected", len(i.affected_urls)),
                "example_urls": i.affected_urls[:3],
                "effort": i.effort.value,
                "evidence": {k: v for k, v in i.evidence.items() if k not in ("total_affected",)} or None,
            }
            for i in result.issues[:limit]
        ],
        "competitors": result.competitors or None,
    }


async def generate_insights(result: AuditResult, settings: Settings) -> AIInsights:
    if settings.ai_enabled and (os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN")):
        try:
            return await _claude_insights(result, settings)
        except anthropic.APIStatusError as exc:
            log.warning("Claude API error %s: %s - falling back to heuristic insights", exc.status_code, exc.message)
        except anthropic.APIConnectionError as exc:
            log.warning("Claude connection error: %s - falling back to heuristic insights", exc)
        except Exception:  # never fail the audit because of the AI layer
            log.exception("AI insight generation failed - falling back to heuristic insights")
    return heuristic_insights(result)


async def _claude_insights(result: AuditResult, settings: Settings) -> AIInsights:
    client = anthropic.AsyncAnthropic()
    findings = json.dumps(_compact_findings(result, settings.ai_max_issues_in_prompt), default=str)
    response = await client.beta.messages.parse(
        model=settings.ai_model,
        max_tokens=16000,
        system=SYSTEM_PROMPT,
        output_config={"effort": settings.ai_effort},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        messages=[{"role": "user", "content": f"<audit_findings>\n{findings}\n</audit_findings>\n\nWrite the strategy section."}],
        output_format=_AIOutput,
    )
    if response.stop_reason == "refusal" or response.parsed_output is None:
        log.warning("Claude returned no parsed output (stop_reason=%s)", response.stop_reason)
        return heuristic_insights(result)
    out = response.parsed_output
    return AIInsights(
        executive_summary=out.executive_summary,
        top_priorities=out.top_priorities,
        quick_wins=out.quick_wins,
        content_opportunities=out.content_opportunities,
        ai_search_recommendations=out.ai_search_recommendations,
        roadmap_30_60_90={"30_days": out.days_30, "60_days": out.days_60, "90_days": out.days_90},
        generated_by=response.model,
    )


def heuristic_insights(result: AuditResult) -> AIInsights:
    issues = result.issues
    crit = [i for i in issues if i.severity == Severity.critical]
    high = [i for i in issues if i.severity == Severity.high]
    weakest = sorted(result.category_scores, key=lambda c: c.score)[:2]
    weakest_txt = ", ".join(f"{c.category.value.replace('_', ' ')} ({c.score})" for c in weakest)
    summary = (
        f"The site scores {result.overall_score}/100 (grade {result.grade}) across {result.stats.get('pages_crawled', 0)} crawled pages. "
        f"{len(crit)} critical and {len(high)} high-severity issues were found. "
        f"Weakest areas: {weakest_txt}. "
        "Fix critical crawl/indexing blockers first, then on-page fundamentals, then content depth and structured data."
    )
    fmt = lambda i: f"{i.title} - {i.recommendation} ({i.evidence.get('total_affected', len(i.affected_urls))} page(s))"  # noqa: E731
    quick = [i for i in issues if i.effort == Effort.low and i.severity in (Severity.critical, Severity.high, Severity.medium)]
    ai_issues = [i for i in issues if i.category.value in ("ai_readiness", "structured_data")]
    content = [i for i in issues if i.category.value in ("content", "competitor")]
    return AIInsights(
        executive_summary=summary,
        top_priorities=[fmt(i) for i in issues[:6]],
        quick_wins=[fmt(i) for i in quick[:5]],
        content_opportunities=[i.recommendation for i in content[:5]],
        ai_search_recommendations=[i.recommendation for i in ai_issues[:5]],
        roadmap_30_60_90={
            "30_days": [i.title for i in issues if i.severity in (Severity.critical, Severity.high)][:6],
            "60_days": [i.title for i in issues if i.severity == Severity.medium][:6],
            "90_days": [i.title for i in issues if i.severity in (Severity.low, Severity.info) or i.effort == Effort.high][:6],
        },
        generated_by="heuristic",
    )
