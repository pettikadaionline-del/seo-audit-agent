from app.audits import performance
from app.audits.base import AuditContext
from app.crawler.engine import SiteMeta
from app.crawler.pagespeed import parse_psi
from app.crawler.parser import PageData

PSI = {
    "loadingExperience": {
        "overall_category": "SLOW",
        "metrics": {
            "LARGEST_CONTENTFUL_PAINT_MS": {"percentile": 4600, "category": "SLOW"},
            "CUMULATIVE_LAYOUT_SHIFT_SCORE": {"percentile": 5, "category": "FAST"},
            "INTERACTION_TO_NEXT_PAINT": {"percentile": 320, "category": "AVERAGE"},
        },
    },
    "lighthouseResult": {
        "categories": {"performance": {"score": 0.38}},
        "audits": {
            "largest-contentful-paint": {"numericValue": 6100, "displayValue": "6.1 s", "score": 0.1},
            "render-blocking-resources": {"title": "Eliminate render-blocking resources", "details": {"type": "opportunity", "overallSavingsMs": 900}},
        },
    },
}


def test_parse_psi_separates_field_and_lab():
    out = parse_psi(PSI)
    assert out["field_url"]["metrics"]["LCP"]["p75"] == 4600
    assert out["field_url"]["metrics"]["CLS"]["p75"] == 0.05  # CrUX reports CLS x100
    assert out["field_origin"] is None
    assert out["lab"]["performance_score"] == 38
    assert out["lab"]["opportunities"][0]["savings_ms"] == 900


def test_field_findings_use_real_user_thresholds():
    psi = {"available": True, "url": "https://shop.example/", **parse_psi(PSI)}
    page = PageData(url="https://shop.example/", final_url="https://shop.example/", status=200, content_type="text/html", ttfb_ms=200, html_bytes=5000)
    ctx = AuditContext(meta=SiteMeta(start_url=page.url, root="https://shop.example", https=True), pages=[page], performance=psi)
    fs = {f.check_id: f for f in performance.run(ctx)}
    assert fs["perf.field_lcp"].severity.value == "high"      # 4600 > 4000 poor threshold
    assert fs["perf.field_inp"].severity.value == "medium"    # 200 < 320 <= 500
    assert "perf.field_cls" not in fs                         # 0.05 is good
    assert fs["perf.field_lcp"].evidence[0]["source"] == "CrUX field"
    assert "perf.lab_score_low" in fs
