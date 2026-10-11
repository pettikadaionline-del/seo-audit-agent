"""Google PageSpeed Insights client.

Returns two clearly separated datasets:
- field: real-user Chrome UX Report (CrUX) data at the 75th percentile, if Google has enough traffic data
- lab:   a single simulated Lighthouse run (mobile), useful for debugging but not what users experience
"""

import httpx

from app.core.config import Settings

PSI_URL = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"

FIELD_METRICS = {
    "LARGEST_CONTENTFUL_PAINT_MS": ("LCP", "ms"),
    "INTERACTION_TO_NEXT_PAINT": ("INP", "ms"),
    "CUMULATIVE_LAYOUT_SHIFT_SCORE": ("CLS", ""),
    "EXPERIMENTAL_TIME_TO_FIRST_BYTE": ("TTFB", "ms"),
    "FIRST_CONTENTFUL_PAINT_MS": ("FCP", "ms"),
}
LAB_AUDITS = {
    "largest-contentful-paint": "LCP",
    "cumulative-layout-shift": "CLS",
    "total-blocking-time": "TBT",
    "first-contentful-paint": "FCP",
    "speed-index": "Speed Index",
}


def _field(block: dict | None) -> dict | None:
    if not block or not block.get("metrics"):
        return None
    out = {"overall": block.get("overall_category"), "metrics": {}}
    for key, (name, unit) in FIELD_METRICS.items():
        m = block["metrics"].get(key)
        if m:
            value = m.get("percentile")
            if name == "CLS" and value is not None:
                value = value / 100  # CrUX reports CLS x100
            out["metrics"][name] = {"p75": value, "unit": unit, "category": m.get("category")}
    return out


def parse_psi(data: dict) -> dict:
    lh = data.get("lighthouseResult", {})
    audits = lh.get("audits", {})
    lab = {
        "performance_score": round((lh.get("categories", {}).get("performance", {}).get("score") or 0) * 100),
        "metrics": {
            name: {"value": audits[k].get("numericValue"), "display": audits[k].get("displayValue"), "score": audits[k].get("score")}
            for k, name in LAB_AUDITS.items() if k in audits
        },
        "opportunities": [
            {"id": k, "title": a.get("title"), "savings_ms": round(a.get("details", {}).get("overallSavingsMs") or 0)}
            for k, a in audits.items()
            if a.get("details", {}).get("type") == "opportunity" and (a.get("details", {}).get("overallSavingsMs") or 0) > 100
        ][:8],
    }
    return {
        "field_url": _field(data.get("loadingExperience")),
        "field_origin": _field(data.get("originLoadingExperience")),
        "lab": lab,
    }


async def run_pagespeed(url: str, settings: Settings, strategy: str = "mobile") -> dict:
    params = {"url": url, "strategy": strategy, "category": "performance"}
    if settings.pagespeed_api_key:
        params["key"] = settings.pagespeed_api_key
    try:
        async with httpx.AsyncClient(timeout=90) as client:
            r = await client.get(PSI_URL, params=params)
        if r.status_code != 200:
            return {"available": False, "error": f"PageSpeed API returned HTTP {r.status_code}"}
        return {"available": True, "url": url, "strategy": strategy, **parse_psi(r.json())}
    except httpx.HTTPError as exc:
        return {"available": False, "error": f"PageSpeed API unreachable: {type(exc).__name__}"}
