from dataclasses import dataclass, field
from urllib.robotparser import RobotFileParser

AI_CRAWLERS = [
    "GPTBot",
    "OAI-SearchBot",
    "ChatGPT-User",
    "ClaudeBot",
    "Claude-SearchBot",
    "PerplexityBot",
    "Google-Extended",
    "CCBot",
    "Applebot-Extended",
    "Bingbot",
]


@dataclass
class RobotsInfo:
    url: str
    status: int | None
    exists: bool
    raw: str = ""
    sitemaps: list[str] = field(default_factory=list)
    crawl_delay: float | None = None
    parser: RobotFileParser | None = None

    def allowed(self, user_agent: str, url: str) -> bool:
        if not self.parser:
            return True
        return self.parser.can_fetch(user_agent, url)

    def ai_access(self, site_root: str) -> dict[str, bool]:
        return {bot: self.allowed(bot, site_root) for bot in AI_CRAWLERS}


def parse_robots(url: str, status: int | None, text: str, our_agent: str) -> RobotsInfo:
    if status is None or status >= 400 or not text.strip():
        # 4xx => crawl everything (Google behaviour); 5xx/unreachable we also treat as allow
        # but record that the file is missing.
        return RobotsInfo(url=url, status=status, exists=False)
    parser = RobotFileParser()
    parser.parse(text.splitlines())
    sitemaps = []
    for line in text.splitlines():
        if line.lower().startswith("sitemap:"):
            sitemaps.append(line.split(":", 1)[1].strip())
    delay = parser.crawl_delay(our_agent)
    return RobotsInfo(
        url=url,
        status=status,
        exists=True,
        raw=text[:20000],
        sitemaps=sitemaps,
        crawl_delay=float(delay) if delay else None,
        parser=parser,
    )
