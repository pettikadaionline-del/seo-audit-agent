"""Agent G: AI-search readiness (GEO / AEO).

Checks how easily AI answer engines (Google AI Overviews, ChatGPT search,
Perplexity, Claude) can crawl, understand and cite the site.
"""
from __future__ import annotations

from urllib.robotparser import RobotFileParser

from app.agents.base import AuditAgent, html_pages, is_noindex
from app.agents.structured_data import iter_entities, types_of
from app.models import Category, Effort, Issue, PageData, Severity, SiteContext

AI_CRAWLERS = ["GPTBot", "OAI-SearchBot", "ChatGPT-User", "ClaudeBot", "Claude-SearchBot", "PerplexityBot", "Google-Extended", "CCBot"]
SEARCH_AI = ["OAI-SearchBot", "Claude-SearchBot", "PerplexityBot", "ChatGPT-User"]


class AIReadinessAgent(AuditAgent):
    category = Category.ai_readiness
    name = "AI Search Readiness"

    def run(self, pages: list[PageData], site: SiteContext) -> list[Issue]:
        out: list[Issue] = []
        ok = [p for p in html_pages(pages) if not is_noindex(p)]

        blocked: list[str] = []
        if site.robots_txt:
            rp = RobotFileParser()
            rp.parse(site.robots_txt.splitlines())
            blocked = [bot for bot in AI_CRAWLERS if not rp.can_fetch(bot, f"{site.origin}/")]
        self.stats = {"ai_crawlers_blocked": blocked, "llms_txt": site.llms_txt_found}
        search_blocked = [b for b in blocked if b in SEARCH_AI]
        if search_blocked:
            out.append(self.issue("crawlers.search_blocked", Severity.high, "AI search crawlers blocked in robots.txt",
                f"robots.txt blocks {', '.join(search_blocked)}. These bots fetch pages to cite them in AI search answers; "
                "blocking them removes you from those results.",
                "Allow AI *search* bots (OAI-SearchBot, Claude-SearchBot, PerplexityBot). You can still block training-only bots "
                "(GPTBot, CCBot, Google-Extended) if you prefer.",
                [f"{site.origin}/robots.txt"], impact=7, effort=Effort.low, blocked=blocked))
        elif blocked:
            out.append(self.issue("crawlers.training_blocked", Severity.info, "AI training crawlers blocked",
                f"robots.txt blocks {', '.join(blocked)} (training crawlers). This is a business choice; search visibility is unaffected.",
                "No action needed unless you want brand knowledge in model training data.",
                [f"{site.origin}/robots.txt"], impact=1, effort=Effort.low, blocked=blocked))

        if not site.llms_txt_found:
            out.append(self.issue("llms_txt", Severity.info, "No /llms.txt file",
                "llms.txt is an emerging (not yet standard) convention summarising your site for LLMs. Low cost, speculative benefit.",
                "Optionally add /llms.txt with a short brand description and links to key pages.",
                [f"{site.origin}/llms.txt"], impact=1, effort=Effort.low))
        if not ok:
            return out

        js_shell = [p.url for p in ok if p.word_count < 50 and p.scripts_total >= 5]
        if js_shell:
            out.append(self.issue("js_rendering", Severity.high, "Content appears to require JavaScript",
                "These pages have little text in the raw HTML but many scripts. Most AI crawlers do not execute JavaScript, "
                "so they see an empty page.",
                "Use server-side rendering or static generation for primary content.",
                js_shell, impact=8, effort=Effort.high))

        no_q = [p for p in ok if p.word_count >= 400 and p.question_headings == 0]
        if len(no_q) >= max(2, len(ok) // 3):
            out.append(self.issue("answer_format", Severity.medium, "Content not structured as answers",
                "Long pages have no question-style headings. AI engines favour content with clear questions followed by "
                "concise 40-60 word answers.",
                "Add question-led H2/H3s (What is..., How to..., Why...) each followed by a direct, quotable answer, then detail.",
                [p.url for p in no_q], impact=5, effort=Effort.medium))

        no_lists = [p.url for p in ok if p.word_count >= 600 and p.lists_count == 0 and p.tables_count == 0]
        if no_lists:
            out.append(self.issue("scannability", Severity.low, "Long content without lists or tables",
                "Bullets and tables are easy for LLMs to extract and cite.",
                "Break key facts, steps, specs and comparisons into lists and tables.", no_lists, impact=3, effort=Effort.low))

        home = ok[0]
        org = [e for e in iter_entities(home.json_ld) if set(types_of(e)) & {"Organization", "LocalBusiness", "Corporation", "Store", "OnlineStore"}]
        if not org or not any(e.get("sameAs") for e in org):
            out.append(self.issue("entity", Severity.medium, "Brand entity not clearly defined",
                "No Organization schema with sameAs links on the homepage. AI engines use these to connect your site with your "
                "social profiles, marketplace listings and reviews - building the entity they cite.",
                "Add Organization JSON-LD with sameAs (Instagram, YouTube, LinkedIn, Amazon store, Wikipedia/Wikidata if any).",
                [home.url], impact=5, effort=Effort.low))

        if not any(("/about" in p.url or "about-us" in p.url) for p in pages):
            out.append(self.issue("about_page", Severity.medium, "No About page found",
                "AI engines and Google's quality raters look for who is behind a site (E-E-A-T).",
                "Publish an About page with founder story, location, credentials, contact details.",
                [site.origin], impact=4, effort=Effort.low))

        stale = [p.url for p in ok if p.word_count >= 600 and not p.has_date]
        if len(stale) >= 3:
            out.append(self.issue("freshness", Severity.low, "No freshness signals on long-form pages",
                "AI answer engines prefer recently updated sources.",
                "Show 'Last updated' dates and keep dateModified in schema current.", stale, impact=3, effort=Effort.low))
        return out
