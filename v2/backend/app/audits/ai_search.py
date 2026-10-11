"""AI search readiness (Google AI Overviews, ChatGPT search, Perplexity, Claude).

There is no published ranking formula for AI answers. These checks cover the
observable preconditions: crawler access, extractable content, entity clarity
and trust signals. Passing them improves the odds of being used as a source;
it never guarantees citation."""

from app.audits.base import AuditContext, Category, Finding, Severity, finding

C = Category.ai_search

SEARCH_BOTS = ["OAI-SearchBot", "ChatGPT-User", "Claude-SearchBot", "PerplexityBot", "Bingbot"]
TRAINING_BOTS = ["GPTBot", "ClaudeBot", "Google-Extended", "CCBot", "Applebot-Extended"]
TRUST_PAGES = {"about": ("about", "our-story", "who-we-are"), "contact": ("contact",), "policy": ("privacy", "terms", "refund", "shipping", "returns")}


def run(ctx: AuditContext) -> list[Finding]:
    out: list[Finding] = []
    meta = ctx.meta
    pages = ctx.indexable_pages

    if meta.robots and meta.robots.exists:
        access = meta.robots.ai_access(meta.start_url)
        blocked_search = [b for b in SEARCH_BOTS if not access.get(b, True)]
        blocked_training = [b for b in TRAINING_BOTS if not access.get(b, True)]
        if blocked_search:
            out.append(finding("ai.search_bots_blocked", C, "robots.txt blocks AI search crawlers", Severity.high,
                               f"Blocked: {', '.join(blocked_search)}. These bots fetch pages to cite them in AI search answers (ChatGPT search, Perplexity, Claude, Copilot). Blocking them removes you from those answers.",
                               "Unless this is a deliberate business decision, allow these user agents in robots.txt. "
                               "Search/retrieval bots are separate from training bots, so you can allow one and block the other.",
                               [(meta.robots.url, {"blocked_user_agents": blocked_search})], site_level=True, effort=1))
        if blocked_training:
            out.append(finding("ai.training_bots_blocked", C, "robots.txt blocks AI training crawlers", Severity.info,
                               f"Blocked: {', '.join(blocked_training)}. This is a legitimate policy choice; it opts your content out of model training and does not by itself remove you from AI search answers.",
                               "No action needed if intentional. Revisit if brand visibility in AI assistants matters more than training opt-out.",
                               [(meta.robots.url, {"blocked_user_agents": blocked_training})], site_level=True, effort=1, confidence="medium"))

    if not meta.llms_txt:
        out.append(finding("ai.no_llms_txt", C, "No llms.txt file", Severity.info,
                           "llms.txt is an emerging, unofficial proposal for a curated, markdown map of your key pages for LLMs. Adoption by AI platforms is limited and unconfirmed; treat it as low-cost, low-certainty.",
                           "Optional: publish /llms.txt listing your most important pages (products, policies, FAQs) with one-line descriptions.",
                           [(meta.root + "/llms.txt", {"found": False})], site_level=True, effort=1, confidence="medium"))

    if not pages:
        return out

    js_only = [(p.url, {"word_count": p.word_count}) for p in pages if p.word_count < 80]
    if len(js_only) > 0.3 * len(pages):
        out.append(finding("ai.little_extractable_text", C, "Little text available to AI crawlers", Severity.high,
                           "Most AI crawlers do not run JavaScript. These pages have under 80 words in the raw HTML, so there is little for them to read, quote or cite.",
                           "Make sure key content (product descriptions, FAQs, policies) is in the server-rendered HTML.",
                           js_only, effort=3, confidence="medium"))

    q_pages = [p for p in pages if p.question_headings > 0]
    faq_schema = any(any("FAQPage" in str(i.get("@type")) for i in p.json_ld) for p in pages)
    if not q_pages and not faq_schema:
        out.append(finding("ai.no_question_content", C, "No question-and-answer style content", Severity.medium,
                           "No headings phrased as questions and no FAQ markup were found. AI answers are triggered by questions; pages that state a question and answer it directly in the next 40–60 words are easier to extract.",
                           "Add FAQ sections to product/category pages using real customer questions (shelf life, shipping abroad, ingredients, storage), each answered in 2–3 direct sentences.",
                           [(p.url, {"question_headings": 0}) for p in pages[:15]], effort=2, confidence="medium"))

    articles = [p for p in pages if p.word_count >= 500]
    no_author = [(p.url, {"author_signal": False, "date_signal": p.has_date}) for p in articles if not p.has_author]
    if no_author and len(no_author) >= max(1, len(articles) // 2):
        out.append(finding("ai.no_author_signals", C, "Long-form pages lack author / expertise signals", Severity.low,
                           "No author markup or byline was detected on content pages. Clear authorship and expertise (E-E-A-T) help both Google and AI systems judge trustworthiness.",
                           "Add a visible byline with a short author bio, and `author` in Article JSON-LD.",
                           no_author, effort=2, confidence="medium"))
    no_date = [(p.url, {"date_signal": False}) for p in articles if not p.has_date]
    if no_date and len(no_date) >= max(1, len(articles) // 2):
        out.append(finding("ai.no_dates", C, "Content pages show no publish/update dates", Severity.low,
                           "AI search systems favour content they can tell is current.",
                           "Show 'last updated' dates on articles and guides and include dateModified in structured data.",
                           no_date, effort=1, confidence="medium"))

    urls = " ".join(p.url.lower() for p in ctx.pages)
    missing_trust = [name for name, keys in TRUST_PAGES.items() if not any(k in urls for k in keys)]
    if missing_trust:
        out.append(finding("ai.trust_pages", C, "Trust pages not found in crawl", Severity.medium,
                           f"No {', '.join(missing_trust)} page was found among crawled URLs. About, contact and policy pages are basic trust signals for users, Google's quality raters and AI systems.",
                           "Make sure About, Contact and policy pages (shipping, returns, privacy) exist and are linked from the footer.",
                           [(meta.start_url, {"missing": missing_trust})], site_level=True, effort=2, confidence="medium"))

    home = ctx.page_by_url.get(meta.start_url)
    if home:
        same_as = [i.get("sameAs") for i in home.json_ld if i.get("sameAs")]
        if not same_as:
            out.append(finding("ai.no_entity_links", C, "Brand entity not linked to external profiles", Severity.low,
                               "No `sameAs` links in the homepage schema. sameAs connects your site to your social and marketplace profiles so engines can recognise one brand entity.",
                               "Add sameAs (Instagram, Facebook, YouTube, LinkedIn, Amazon/marketplace store, Wikipedia/Wikidata if any) to your Organization schema.",
                               [(home.url, {"sameAs": None})], site_level=True, effort=1))
    return out
