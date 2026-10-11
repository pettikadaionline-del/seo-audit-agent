from app.audits.base import AuditContext, Category, Finding, Severity, finding

C = Category.content

THIN_WORDS = 300


def jaccard(a: list[int], b: list[int]) -> float:
    if not a or not b:
        return 0.0
    sa, sb = set(a), set(b)
    return len(sa & sb) / len(sa | sb)


def run(ctx: AuditContext) -> list[Finding]:
    out: list[Finding] = []
    pages = ctx.indexable_pages

    thin = [(p.url, {"word_count": p.word_count}) for p in pages if p.word_count < THIN_WORDS]
    if thin:
        sev = Severity.high if len(thin) > 0.5 * max(1, len(pages)) else Severity.medium
        out.append(finding(
            "content.thin", C, f"Thin content (under {THIN_WORDS} words)", sev,
            "Pages with little main content struggle to rank and give AI answer engines nothing to quote. "
            "Word count is a proxy, not a target: category and contact pages can be short by design.",
            "For pages that should rank, add genuinely useful content: specifics, FAQs, how-to guidance, comparisons, original data or examples. "
            "Merge or noindex near-empty pages that have no search purpose.",
            thin, effort=3, confidence="medium",
        ))

    near = []
    seen_pairs = set()
    candidates = [p for p in pages if len(p.shingles) >= 20]
    for i, a in enumerate(candidates):
        for b in candidates[i + 1 :]:
            if a.content_hash == b.content_hash:
                continue  # exact duplicates reported by technical audit
            sim = jaccard(a.shingles, b.shingles)
            if sim >= 0.8 and (a.url, b.url) not in seen_pairs:
                seen_pairs.add((a.url, b.url))
                near.append((a.url, {"similar_to": b.url, "similarity": round(sim, 2)}))
                near.append((b.url, {"similar_to": a.url, "similarity": round(sim, 2)}))
    if near:
        out.append(finding(
            "content.near_duplicate", C, "Near-duplicate content", Severity.medium,
            "These page pairs share 80%+ of their text (shingle similarity), which dilutes relevance. Typical cause: product variants or location pages built from one template.",
            "Differentiate each page with unique copy, or consolidate variants into one page with options and canonicalise the rest.",
            near, effort=3, confidence="medium",
        ))

    hard = [(p.url, {"flesch_reading_ease": p.readability}) for p in pages if p.readability is not None and p.readability < 30]
    if hard:
        out.append(finding(
            "content.readability", C, "Content is hard to read", Severity.low,
            "Flesch Reading Ease below 30 (university level). Long sentences and jargon reduce engagement, especially on mobile. Score is only meaningful for English text.",
            "Shorten sentences, use plain words, break text into short paragraphs and bullet lists.",
            hard, effort=2, confidence="medium",
        ))

    no_h2 = [(p.url, {"word_count": p.word_count, "subheadings": 0}) for p in pages if p.word_count > 600 and not any(l == 2 for l, _ in p.headings)]
    if no_h2:
        out.append(finding(
            "content.no_structure", C, "Long pages without subheadings", Severity.low,
            "600+ word pages with no H2 sections are hard to scan and harder for search engines to split into passages.",
            "Break content into sections with descriptive H2/H3 subheadings.",
            no_h2, effort=2,
        ))

    big = [p for p in ctx.html_pages if p.html_bytes > 0]
    low_ratio = []
    for p in big:
        text_bytes = len(p.text_sample) if p.word_count < 250 else p.word_count * 6
        ratio = text_bytes / p.html_bytes
        if ratio < 0.05 and p.html_bytes > 50_000:
            low_ratio.append((p.url, {"text_to_html_ratio": round(ratio, 3), "html_kb": round(p.html_bytes / 1024)}))
    if low_ratio:
        out.append(finding(
            "content.text_ratio", C, "Very low text-to-HTML ratio", Severity.info,
            "Under 5% of the page weight is visible text. Usually heavy theme code or inline scripts; not a ranking factor by itself, but often goes with thin content and slow pages.",
            "Trim unused theme code and inline scripts; make sure meaningful text is rendered in the HTML, not only via JavaScript.",
            low_ratio, effort=3, confidence="medium",
        ))

    js_rendered = [(p.url, {"word_count": p.word_count, "scripts": p.scripts_total}) for p in ctx.html_pages if p.word_count < 50 and p.scripts_total >= 5]
    if js_rendered:
        out.append(finding(
            "content.js_dependent", C, "Content may depend on JavaScript rendering", Severity.medium,
            "The raw HTML has almost no text but many scripts. Google can render JavaScript (with delay), but many AI crawlers and social previews do not execute it.",
            "Use server-side rendering or pre-rendering so the main content is in the initial HTML.",
            js_rendered, effort=4, confidence="medium",
        ))
    return out
