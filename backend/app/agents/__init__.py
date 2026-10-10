from app.agents.ai_readiness import AIReadinessAgent
from app.agents.base import AuditAgent
from app.agents.competitor import CompetitorAgent, profile_site
from app.agents.content import ContentAgent
from app.agents.links import LinksAgent
from app.agents.onpage import OnPageAgent
from app.agents.performance import PerformanceAgent
from app.agents.structured_data import StructuredDataAgent
from app.agents.technical import TechnicalAgent


def default_agents() -> list[AuditAgent]:
    return [
        TechnicalAgent(),
        OnPageAgent(),
        ContentAgent(),
        LinksAgent(),
        PerformanceAgent(),
        StructuredDataAgent(),
        AIReadinessAgent(),
    ]


__all__ = ["AuditAgent", "CompetitorAgent", "default_agents", "profile_site"]
