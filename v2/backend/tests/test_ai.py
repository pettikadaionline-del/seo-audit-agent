import json
from types import SimpleNamespace

from app.ai import recommender
from app.core.config import Settings

FINDINGS = [
    {"id": "F001", "check_id": "tech.no_https", "category": "technical", "title": "No HTTPS", "severity": "critical",
     "description": "d", "recommendation": "Install TLS", "affected_urls": ["http://x/"], "evidence": [{"url": "http://x/"}],
     "priority": {"bucket": "critical", "impact": 5, "effort": 2, "priority_score": 8}},
    {"id": "F002", "check_id": "onpage.title_missing", "category": "onpage", "title": "Missing titles", "severity": "high",
     "description": "d2", "recommendation": "Add titles", "affected_urls": ["http://x/a"], "evidence": [],
     "priority": {"bucket": "quick_win", "impact": 4, "effort": 1, "priority_score": 7}},
]
SUMMARY = {"url": "http://x/", "overall_score": 55, "pages_audited": 2}


def fake_client(payload=None, stop_reason="end_turn", capture=None):
    class Messages:
        async def create(self, **kwargs):
            if capture is not None:
                capture.update(kwargs)
            text = json.dumps(payload) if payload is not None else ""
            return SimpleNamespace(stop_reason=stop_reason, model="test-model",
                                   content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=text)],
                                   usage=SimpleNamespace(input_tokens=10, output_tokens=20))

    class Client:
        def __init__(self, **kwargs):
            self.beta = SimpleNamespace(messages=Messages())

    return Client


async def test_no_key_uses_rules():
    out = await recommender.generate_ai_report(SUMMARY, FINDINGS, Settings(anthropic_api_key=None))
    assert out["source"] == "rules"
    assert out["findings"]["F001"]["fix_steps"] == ["Install TLS"]
    assert any("ANTHROPIC_API_KEY" in c for c in out["caveats"])


async def test_ai_output_merged_and_unknown_ids_dropped(monkeypatch):
    payload = {
        "executive_summary": "Fix HTTPS first.",
        "top_priorities": ["Enable HTTPS"],
        "findings": [
            {"finding_id": "F001", "why_it_matters": "Trust", "fix_steps": ["a", "b"], "code_example": None, "business_impact": "More trust"},
            {"finding_id": "F999", "why_it_matters": "invented", "fix_steps": ["x"], "code_example": None, "business_impact": ""},
        ],
        "content_opportunities": [{"title": "Shelf-life guide", "rationale": "Asked often"}],
        "caveats": ["Small sample"],
    }
    captured = {}
    monkeypatch.setattr(recommender.anthropic, "AsyncAnthropic", fake_client(payload, capture=captured))
    out = await recommender.generate_ai_report(SUMMARY, FINDINGS, Settings(anthropic_api_key="sk-test"))
    assert out["source"] == "ai"
    assert out["findings"]["F001"]["fix_steps"] == ["a", "b"]
    assert out["findings"]["F002"]["fix_steps"] == ["Add titles"]  # not covered by AI -> rule-based kept
    assert "F999" not in out["findings"]
    # Request shape: structured output schema, adaptive thinking, refusal fallback, untrusted data fenced.
    assert captured["output_config"]["format"]["type"] == "json_schema"
    assert captured["thinking"] == {"type": "adaptive"}
    assert captured["fallbacks"] == "default"
    assert "<site_data>" in captured["messages"][0]["content"]


async def test_refusal_falls_back(monkeypatch):
    monkeypatch.setattr(recommender.anthropic, "AsyncAnthropic", fake_client(None, stop_reason="refusal"))
    out = await recommender.generate_ai_report(SUMMARY, FINDINGS, Settings(anthropic_api_key="sk-test"))
    assert out["source"] == "rules"
    assert any("refusal" in c for c in out["caveats"])


async def test_invalid_json_falls_back(monkeypatch):
    monkeypatch.setattr(recommender.anthropic, "AsyncAnthropic", fake_client({"executive_summary": 1}))
    out = await recommender.generate_ai_report(SUMMARY, FINDINGS, Settings(anthropic_api_key="sk-test"))
    assert out["source"] == "rules"
