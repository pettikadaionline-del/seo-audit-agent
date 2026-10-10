"""Transparent scoring and prioritisation.

Category score: start at 100, subtract a severity penalty per issue, scaled by
how much of the site is affected (site-wide problems hurt more than one-offs).
Overall score: weighted mean of category scores.
Priority: impact x severity x reach / effort - the action-center sort key.
"""
from __future__ import annotations

from app.models import Category, CategoryScore, Effort, Issue, Severity

SEVERITY_PENALTY = {Severity.critical: 30, Severity.high: 15, Severity.medium: 7, Severity.low: 3, Severity.info: 0}
SEVERITY_MULT = {Severity.critical: 3.0, Severity.high: 2.0, Severity.medium: 1.3, Severity.low: 0.8, Severity.info: 0.3}
EFFORT_COST = {Effort.low: 1.0, Effort.medium: 2.0, Effort.high: 3.5}
WEIGHTS = {
    Category.technical: 0.22,
    Category.onpage: 0.18,
    Category.content: 0.16,
    Category.links: 0.10,
    Category.performance: 0.12,
    Category.structured_data: 0.10,
    Category.ai_readiness: 0.08,
    Category.competitor: 0.04,
}


def _reach(issue: Issue, total_pages: int) -> float:
    total = issue.evidence.get("total_affected", len(issue.affected_urls))
    if total_pages <= 0:
        return 1.0
    return min(1.0, max(total, 1) / total_pages)


def prioritise(issues: list[Issue], total_pages: int) -> list[Issue]:
    for i in issues:
        reach = 0.5 + 0.5 * _reach(i, total_pages)
        i.priority_score = round(i.impact * SEVERITY_MULT[i.severity] * reach / EFFORT_COST[i.effort] * 10, 1)
    return sorted(issues, key=lambda i: i.priority_score, reverse=True)


def score(issues: list[Issue], total_pages: int, categories: list[Category]) -> tuple[int, list[CategoryScore]]:
    results: list[CategoryScore] = []
    for cat in categories:
        cat_issues = [i for i in issues if i.category == cat]
        penalty = sum(SEVERITY_PENALTY[i.severity] * (0.4 + 0.6 * _reach(i, total_pages)) for i in cat_issues)
        results.append(CategoryScore(category=cat, score=max(0, round(100 - penalty)), issues=len(cat_issues), weight=WEIGHTS[cat]))
    wsum = sum(r.weight for r in results) or 1
    overall = round(sum(r.score * r.weight for r in results) / wsum)
    return overall, results


def grade(overall: int) -> str:
    for threshold, g in ((90, "A"), (80, "B"), (65, "C"), (50, "D")):
        if overall >= threshold:
            return g
    return "F"
