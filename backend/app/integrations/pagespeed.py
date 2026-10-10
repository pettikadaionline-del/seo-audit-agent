"""Optional Google PageSpeed Insights (Lighthouse lab data) for the homepage."""
from __future__ import annotations

from typing import Any

import httpx

PSI_ENDPOINT = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"


async def fetch_pagespeed(url: str, api_key: str, strategy: str = "mobile") -> dict[str, Any]:
    params = {"url": url, "key": api_key, "strategy": strategy, "category": "performance"}
    try:
        async with httpx.AsyncClient(timeout=90) as client:
            r = await client.get(PSI_ENDPOINT, params=params)
            r.raise_for_status()
            data = r.json()
    except httpx.HTTPStatusError as exc:  # message would include the API key in the URL
        return {"error": f"PageSpeed API returned HTTP {exc.response.status_code}"}
    except (httpx.HTTPError, ValueError) as exc:
        return {"error": f"PageSpeed API request failed: {type(exc).__name__}"}
    lh = data.get("lighthouseResult", {})
    audits = lh.get("audits", {})
    num = lambda k: audits.get(k, {}).get("numericValue")  # noqa: E731
    perf = lh.get("categories", {}).get("performance", {}).get("score")
    field = data.get("loadingExperience", {}).get("metrics", {})
    return {
        "strategy": strategy,
        "performance_score": round(perf * 100) if perf is not None else None,
        "metrics": {
            "lcp_ms": num("largest-contentful-paint"),
            "fcp_ms": num("first-contentful-paint"),
            "tbt_ms": num("total-blocking-time"),
            "cls": num("cumulative-layout-shift"),
            "speed_index_ms": num("speed-index"),
        },
        "field_data": {k: v.get("category") for k, v in field.items()} or None,
    }
