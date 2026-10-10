from types import SimpleNamespace

import anthropic

from app.ai import advisor
from app.config import Settings
from app.models import AuditResult, AuditStatus


def _result() -> AuditResult:
    return AuditResult(id="a", url="https://x.example/", status=AuditStatus.completed, overall_score=70, grade="C",
                       stats={"pages_crawled": 3})


async def test_uses_claude_when_key_present(monkeypatch):
    captured = {}

    class FakeMessages:
        async def parse(self, **kwargs):
            captured.update(kwargs)
            out = advisor._AIOutput(executive_summary="ok", top_priorities=["a"], quick_wins=["b"], content_opportunities=[],
                                    ai_search_recommendations=[], days_30=["x"], days_60=[], days_90=[])
            return SimpleNamespace(stop_reason="end_turn", parsed_output=out, model="claude-opus-5-5")

    fake = SimpleNamespace(beta=SimpleNamespace(messages=FakeMessages()))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.setattr(anthropic, "AsyncAnthropic", lambda: fake)
    ins = await advisor.generate_insights(_result(), Settings(ai_enabled=True))
    assert ins.generated_by == "claude-opus-5-5"
    assert ins.roadmap_30_60_90["30_days"] == ["x"]
    assert captured["model"] == "claude-opus-5-5"
    assert captured["output_format"] is advisor._AIOutput
    assert "<audit_findings>" in captured["messages"][0]["content"]


async def test_falls_back_without_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    ins = await advisor.generate_insights(_result(), Settings(ai_enabled=True))
    assert ins.generated_by == "heuristic" and "70/100" in ins.executive_summary


async def test_falls_back_on_api_error(monkeypatch):
    class Boom:
        async def parse(self, **kwargs):
            raise anthropic.APIConnectionError(request=None)  # type: ignore[arg-type]

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.setattr(anthropic, "AsyncAnthropic", lambda: SimpleNamespace(beta=SimpleNamespace(messages=Boom())))
    ins = await advisor.generate_insights(_result(), Settings(ai_enabled=True))
    assert ins.generated_by == "heuristic"
