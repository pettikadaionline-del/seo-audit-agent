"""Agent C: content quality (thin / duplicate content, E-E-A-T signals, readability)."""
from __future__ import annotations

import re
from collections import defaultdict

from app.agents.base import AuditAgent, html_pages, is_noindex
from app.models import Category, Effort, Issue, PageData, Severity, SiteContext

THIN_WORDS = 300
VERY_THIN_WORDS = 100
SENTENCE_RE = re.compile(r"[.!?]+\s")
SYLLABLE_RE = re.compile(r"[aeiouy]+", re.I)


def flesch_reading_ease(text: str) -> float | None:
    words = re.findall(r"[A-Za-z]+", text)
    if len(words) < 50:
        return None
    sentences = max(1, len(SENTENCE_RE.findall(text)) + 1)
    syllables = sum(max(1, len(SYLLABLE_RE.findall(w))) for w in words)
    return round(206.835 - 1.015 * (len(words) / sentences) - 84.6 * (syllables / len(words)), 1)


class ContentAgent(AuditAgent):
    category = Category.content
    name = "Content Quality"

    def run(self, pages: list[PageData], site: SiteContext) -> list[Issue]:
        out: list[Issue] = []
        ok = [p for p in html_pages(pages) if not is_noindex(p)]
        if not ok:
            return out

        very_thin = [p.url for p in ok if p.word_count < VERY_THIN_WORDS]
        thin = [p.url for p in ok if VERY_THIN_WORDS <= p.word_count < THIN_WORDS]
        if very_thin:
            out.append(self.issue("thin.severe", Severity.high, f"Very thin content (<{VERY_THIN_WORDS} words)",
                "These pages have almost no indexable text. They rarely rank and can drag down site-wide quality perception.",
                "Expand with genuinely useful copy (specs, usage, origin story, FAQs) or noindex/consolidate them. "
                "If the content is rendered by JavaScript, ensure it's server-side rendered.",
                very_thin, impact=7, effort=Effort.medium,
                word_counts={p.url: p.word_count for p in ok if p.url in very_thin[:20]}))
        if thin:
            out.append(self.issue("thin", Severity.medium, f"Thin content ({VERY_THIN_WORDS}-{THIN_WORDS} words)",
                "Pages with limited content struggle to demonstrate topical depth.",
                "Add depth where it serves user intent: comparisons, how-to, ingredients/specs, reviews, FAQs.",
                thin, impact=5, effort=Effort.medium))

        groups: dict[str, list[str]] = defaultdict(list)
        for p in ok:
            if p.content_hash:
                groups[p.content_hash].append(p.url)
        dupes = [g for g in groups.values() if len(g) > 1]
        if dupes:
            out.append(self.issue("duplicate", Severity.high, "Duplicate page content",
                f"{len(dupes)} group(s) of pages have identical body text.",
                "Consolidate duplicates with 301 redirects or rel=canonical to a single preferred URL.",
                [u for g in dupes for u in g], impact=7, effort=Effort.medium, groups=[g[:5] for g in dupes[:10]]))

        # E-E-A-T signals (heuristic): author & date on article-like pages
        articles = [p for p in ok if p.word_count >= 600 or "/blog" in p.url or "/article" in p.url or "/news" in p.url]
        no_author = [p.url for p in articles if not p.has_author]
        no_date = [p.url for p in articles if not p.has_date]
        if no_author:
            out.append(self.issue("eeat.author", Severity.medium, "Long-form content without author attribution",
                "Article-style pages lack a visible author/byline. Author signals support E-E-A-T, especially for YMYL topics.",
                "Add an author byline linked to an author bio page, plus Person schema.",
                no_author, impact=4, effort=Effort.low))
        if no_date:
            out.append(self.issue("eeat.date", Severity.low, "Long-form content without publish/update date",
                "No visible or machine-readable date found. Freshness signals matter for both search and AI answers.",
                "Show 'Published' / 'Updated' dates and add datePublished/dateModified in Article schema.",
                no_date, impact=3, effort=Effort.low))

        hard = {}
        for p in ok:
            score = flesch_reading_ease(p.text_sample)
            if score is not None and score < 30:
                hard[p.url] = score
        if hard:
            out.append(self.issue("readability", Severity.low, "Hard-to-read content",
                "Flesch reading ease below 30 (college-graduate level) on the sampled text.",
                "Shorter sentences, simpler words, more sub-headings and bullet lists.",
                list(hard), impact=2, effort=Effort.medium, scores=dict(list(hard.items())[:20])))

        avg = sum(p.word_count for p in ok) / len(ok)
        blogish = [p for p in ok if any(s in p.url for s in ("/blog", "/article", "/guide", "/news", "/recipe"))]
        if not blogish and len(ok) >= 5:
            out.append(self.issue("strategy.no_editorial", Severity.medium, "No editorial / blog content detected",
                "No blog, guide or article sections were found. Informational content captures top-of-funnel searches "
                "and is the main source material for AI answer engines.",
                "Launch a content hub targeting informational queries in your niche (how-to, origin stories, comparisons, recipes).",
                [site.origin], impact=6, effort=Effort.high, avg_word_count=round(avg)))
        return out
