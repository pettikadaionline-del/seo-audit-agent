"""Transparent scoring and prioritisation.

Category score = 100 − Σ penalties, floored at 0.
  penalty = SEVERITY_POINTS[severity] × reach
  reach   = 1.0 for site-level findings, else 0.4 + 0.6 × (affected pages / pages audited)
Overall score = weighted mean of category scores (weights below; the competitor
category is only included when competitors were benchmarked).

Priority:
  impact (1–5) from severity; medium/high findings affecting ≥50% of pages get +1
  effort (1–5) set per check
  bucket: critical → Critical Fixes; impact ≥ 3 & effort ≤ 2 → Quick Wins;
          impact ≥ 3 → Strategic; else Long-Term
"""

from app.audits.base import CATEGORY_LABELS, Category, Finding, Severity

SEVERITY_POINTS = {Severity.critical: 30, Severity.high: 15, Severity.medium: 7, Severity.low: 3, Severity.info: 0}
SEVERITY_IMPACT = {Severity.critical: 5, Severity.high: 4, Severity.medium: 3, Severity.low: 2, Severity.info: 1}

WEIGHTS = {
    Category.technical: 0.20,
    Category.onpage: 0.15,
    Category.content: 0.15,
    Category.linking: 0.10,
    Category.performance: 0.15,
    Category.structured_data: 0.08,
    Category.ai_search: 0.10,
    Category.competitor: 0.07,
}


def reach(f: Finding, total_pages: int) -> float:
    if f.site_level or total_pages <= 0:
        return 1.0
    return 0.4 + 0.6 * min(1.0, len(f.affected_urls) / total_pages)


def category_scores(findings: list[Finding], total_pages: int, include_competitor: bool) -> dict:
    out = {}
    for cat in Category:
        if cat == Category.competitor and not include_competitor:
            continue
        fs = [f for f in findings if f.category == cat]
        penalty = sum(SEVERITY_POINTS[f.severity] * reach(f, total_pages) for f in fs)
        out[cat.value] = {
            "label": CATEGORY_LABELS[cat],
            "score": max(0, round(100 - penalty)),
            "weight": WEIGHTS[cat],
            "findings": len(fs),
            "by_severity": {s.value: sum(1 for f in fs if f.severity == s) for s in Severity},
        }
    total_w = sum(v["weight"] for v in out.values())
    for v in out.values():
        v["weight"] = round(v["weight"] / total_w, 3)
    return out


def overall_score(cats: dict) -> int:
    return round(sum(v["score"] * v["weight"] for v in cats.values()))


def grade(score: int) -> str:
    return "A" if score >= 90 else "B" if score >= 75 else "C" if score >= 60 else "D" if score >= 40 else "F"


def prioritise(f: Finding, total_pages: int) -> dict:
    impact = SEVERITY_IMPACT[f.severity]
    # Widespread medium/high issues get +1 impact; low/info stay put so polish items don't crowd Quick Wins.
    if not f.site_level and total_pages and len(f.affected_urls) / total_pages >= 0.5 and f.severity in (Severity.medium, Severity.high):
        impact += 1
    effort = f.effort
    if f.severity == Severity.critical:
        bucket = "critical"
    elif impact >= 3 and effort <= 2:
        bucket = "quick_win"
    elif impact >= 3:
        bucket = "strategic"
    else:
        bucket = "long_term"
    return {"impact": impact, "effort": effort, "bucket": bucket, "priority_score": impact * 2 - effort}


BUCKET_LABELS = {
    "critical": "Critical Fixes",
    "quick_win": "Quick Wins",
    "strategic": "Strategic Improvements",
    "long_term": "Long-Term Opportunities",
}
