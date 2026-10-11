from collections import defaultdict

from app.audits.base import AuditContext, Category, Finding, Severity, finding

C = Category.onpage

TITLE_MIN, TITLE_MAX = 30, 60
DESC_MIN, DESC_MAX = 70, 160


def _dupes(pages, attr: str) -> list[tuple[str, dict]]:
    groups: dict[str, list[str]] = defaultdict(list)
    for p in pages:
        value = (getattr(p, attr) or "").strip().lower()
        if value:
            groups[value].append(p.url)
    return [(u, {attr: v[:160], "shared_by": len(us)}) for v, us in groups.items() if len(us) > 1 for u in us]


def run(ctx: AuditContext) -> list[Finding]:
    out: list[Finding] = []
    pages = ctx.indexable_pages

    missing = [(p.url, {"title": None}) for p in pages if not p.title]
    if missing:
        out.append(finding("onpage.title_missing", C, "Missing title tags", Severity.high,
                           "The title tag is the main headline shown in search results and a strong relevance signal.",
                           "Write a unique title (30–60 characters) for each page: primary keyword first, brand last.", missing, effort=1))
    short = [(p.url, {"title": p.title, "length": len(p.title)}) for p in pages if p.title and len(p.title) < TITLE_MIN]
    long_ = [(p.url, {"title": p.title, "length": len(p.title)}) for p in pages if p.title and len(p.title) > TITLE_MAX]
    if short:
        out.append(finding("onpage.title_short", C, "Title tags too short", Severity.low,
                           f"Titles under {TITLE_MIN} characters leave out keywords and context.",
                           "Expand titles to describe the page with its main keyword and a differentiator (e.g. location, benefit).", short, effort=1))
    if long_:
        out.append(finding("onpage.title_long", C, "Title tags likely truncated in results", Severity.low,
                           f"Titles over ~{TITLE_MAX} characters are often cut off in search results.",
                           "Move the most important words to the front and trim to about 60 characters.", long_, effort=1))
    dup = _dupes(pages, "title")
    if dup:
        out.append(finding("onpage.title_duplicate", C, "Duplicate title tags", Severity.medium,
                           "Several pages share the same title, making it hard for search engines to tell which page to rank.",
                           "Give each page a unique title that reflects its specific content.", dup, effort=2))

    missing_d = [(p.url, {"meta_description": None}) for p in pages if not p.meta_description]
    if missing_d:
        out.append(finding("onpage.description_missing", C, "Missing meta descriptions", Severity.medium,
                           "Without one, search engines generate a snippet from the page, often a poor one. Descriptions affect click-through, not rankings directly.",
                           "Write a 70–160 character description per page with a clear benefit and a call to action.", missing_d, effort=1))
    bad_len = [(p.url, {"meta_description": p.meta_description[:170], "length": len(p.meta_description)})
               for p in pages if p.meta_description and not (DESC_MIN <= len(p.meta_description) <= DESC_MAX)]
    if bad_len:
        out.append(finding("onpage.description_length", C, "Meta descriptions too short or too long", Severity.low,
                           f"Aim for {DESC_MIN}–{DESC_MAX} characters so the snippet is informative and not truncated.",
                           "Rewrite to fit the range; lead with the benefit.", bad_len, effort=1))
    dup_d = _dupes(pages, "meta_description")
    if dup_d:
        out.append(finding("onpage.description_duplicate", C, "Duplicate meta descriptions", Severity.low,
                           "Repeated descriptions reduce click-through and suggest templated pages.",
                           "Write page-specific descriptions, starting with your highest-traffic pages.", dup_d, effort=2))

    no_h1 = [(p.url, {"h1_count": 0}) for p in pages if not p.h1]
    multi_h1 = [(p.url, {"h1_count": len(p.h1), "h1": p.h1[:4]}) for p in pages if len(p.h1) > 1]
    if no_h1:
        out.append(finding("onpage.h1_missing", C, "Missing H1 heading", Severity.medium,
                           "The H1 tells users and search engines what the page is about.",
                           "Add one descriptive H1 per page containing the primary topic or keyword.", no_h1, effort=1))
    if multi_h1:
        out.append(finding("onpage.h1_multiple", C, "Multiple H1 headings", Severity.low,
                           "Multiple H1s are valid HTML but blur the page's main topic; often caused by theme logos or sliders.",
                           "Keep one H1 for the main heading and turn the others into H2s.", multi_h1, effort=1, confidence="medium"))

    skips = []
    for p in pages:
        prev = 0
        for level, text in p.headings:
            if prev and level > prev + 1:
                skips.append((p.url, {"jump": f"H{prev} → H{level}", "heading": text[:80]}))
                break
            prev = level
    if skips:
        out.append(finding("onpage.heading_hierarchy", C, "Heading levels skipped", Severity.low,
                           "Skipping levels (e.g. H2 straight to H4) weakens the outline that search engines and screen readers use.",
                           "Use headings in order (H1 → H2 → H3) to reflect the content structure.", skips, effort=1, confidence="medium"))

    alt_missing = []
    total_imgs = 0
    for p in pages:
        imgs = [i for i in p.images if i.src]
        total_imgs += len(imgs)
        missing_alt = [i.src for i in imgs if i.alt is None]
        if missing_alt:
            alt_missing.append((p.url, {"images_without_alt": len(missing_alt), "total_images": len(imgs), "examples": missing_alt[:3]}))
    if alt_missing:
        out.append(finding("onpage.image_alt_missing", C, "Images missing alt text", Severity.medium,
                           "Alt text is how search engines understand images (Google Images traffic) and is required for accessibility.",
                           'Add short, descriptive alt text to meaningful images (product name + key attribute). Use alt="" for purely decorative images.',
                           alt_missing, effort=2))

    no_og = [(p.url, {"missing": [k for k in ("title", "description", "image") if k not in p.og]}) for p in pages
             if any(k not in p.og for k in ("title", "description", "image"))]
    if no_og:
        out.append(finding("onpage.open_graph_missing", C, "Incomplete Open Graph tags", Severity.low,
                           "Open Graph tags control the preview when pages are shared on social networks and messaging apps, which affects social click-through.",
                           "Add og:title, og:description and og:image (1200×630) to every page template.", no_og, effort=1))

    title_eq_h1 = [(p.url, {"title": p.title}) for p in pages if p.title and p.h1 and p.title.strip().lower() == p.h1[0].strip().lower() and len(pages) > 3]
    if len(title_eq_h1) > max(3, len(pages) // 2):
        out.append(finding("onpage.title_equals_h1", C, "Title tags identical to H1 on most pages", Severity.info,
                           "Not an error, but a separate title lets you target an extra keyword variant or add a click-worthy hook.",
                           "Consider writing titles that complement the H1 rather than repeat it.", title_eq_h1, effort=2, confidence="medium"))
    return out
