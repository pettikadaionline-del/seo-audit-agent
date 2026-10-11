"""Structured data audit: JSON-LD syntax and required/recommended properties for
the schema types that drive Google rich results. Passing these checks makes a
page *eligible*; Google never guarantees rich results."""

from app.audits.base import AuditContext, Category, Finding, Severity, finding

C = Category.structured_data

# Based on Google Search Central structured-data docs (required props for rich-result eligibility).
REQUIRED = {
    "Product": [["name"], ["offers", "review", "aggregateRating"]],
    "Article": [["headline"], ["image"], ["datePublished"], ["author"]],
    "BlogPosting": [["headline"], ["image"], ["datePublished"], ["author"]],
    "NewsArticle": [["headline"], ["image"], ["datePublished"], ["author"]],
    "Organization": [["name"], ["url"], ["logo"]],
    "LocalBusiness": [["name"], ["address"]],
    "BreadcrumbList": [["itemListElement"]],
    "FAQPage": [["mainEntity"]],
    "Recipe": [["name"], ["image"]],
    "Event": [["name"], ["startDate"], ["location"]],
    "WebSite": [["name"], ["url"]],
    "Review": [["itemReviewed"], ["author"], ["reviewRating"]],
    "VideoObject": [["name"], ["thumbnailUrl"], ["uploadDate"]],
}
OFFER_REQUIRED = ["price", "priceCurrency"]


def _types(item: dict) -> list[str]:
    t = item.get("@type", [])
    return [x.rsplit("/", 1)[-1] for x in (t if isinstance(t, list) else [t]) if isinstance(x, str)]


def validate_item(item: dict) -> list[str]:
    problems = []
    for t in _types(item):
        rules = REQUIRED.get(t) or (REQUIRED["LocalBusiness"] if t.endswith(("Store", "Restaurant", "Business")) else None)
        for group in rules or []:
            if not any(item.get(k) not in (None, "", []) for k in group):
                problems.append(f"{t}: missing {' or '.join(group)}")
        if t == "Product":
            offers = item.get("offers")
            offer_list = offers if isinstance(offers, list) else [offers] if isinstance(offers, dict) else []
            for o in offer_list:
                if isinstance(o, dict) and o.get("@type", "Offer") == "Offer":
                    for k in OFFER_REQUIRED:
                        if not o.get(k) and o.get(k) != 0:
                            problems.append(f"Product.offers: missing {k}")
    return problems


def run(ctx: AuditContext) -> list[Finding]:
    out: list[Finding] = []
    pages = ctx.indexable_pages
    if not pages:
        return out

    with_sd = [p for p in pages if p.json_ld or p.microdata_types]
    without = [(p.url, {"json_ld_types": [], "microdata_types": []}) for p in pages if not (p.json_ld or p.microdata_types)]
    all_types = sorted({t for p in pages for item in p.json_ld for t in _types(item)} | {t for p in pages for t in p.microdata_types})

    if not with_sd:
        out.append(finding("sd.none", C, "No structured data found on any page", Severity.high,
                           "Structured data (schema.org JSON-LD) helps search engines and AI systems understand entities such as your organisation, products, prices and FAQs, and is required for rich-result eligibility.",
                           "Start with Organization + WebSite on the homepage, Product (with Offer price/currency) on product pages, and BreadcrumbList on inner pages. Validate with Google's Rich Results Test.",
                           without, effort=2))
    elif without:
        out.append(finding("sd.missing_on_pages", C, "Pages without structured data", Severity.low,
                           f"{len(without)} of {len(pages)} indexable pages have no structured data. Types used elsewhere on the site: {', '.join(all_types) or 'none'}.",
                           "Add the relevant schema type to each page template (Product, Article, BreadcrumbList).",
                           without, effort=2, confidence="medium"))

    invalid = [(p.url, {"errors": p.json_ld_errors}) for p in pages if p.json_ld_errors]
    if invalid:
        out.append(finding("sd.invalid_json", C, "Invalid JSON-LD syntax", Severity.high,
                           "Search engines ignore JSON-LD blocks that fail to parse.",
                           "Fix the JSON syntax (trailing commas, unescaped quotes are the usual culprits) and re-test.", invalid, effort=1))

    incomplete = []
    for p in pages:
        problems = [prob for item in p.json_ld for prob in validate_item(item)]
        if problems:
            incomplete.append((p.url, {"problems": sorted(set(problems))[:8]}))
    if incomplete:
        out.append(finding("sd.missing_required", C, "Structured data missing required properties", Severity.medium,
                           "These schema items are missing properties Google requires for rich-result eligibility. Eligibility is necessary but does not guarantee a rich result.",
                           "Add the missing properties listed in the evidence, then validate in the Rich Results Test.", incomplete, effort=2))

    home = ctx.page_by_url.get(ctx.meta.start_url)
    if home and home.status == 200:
        home_types = {t for item in home.json_ld for t in _types(item)}
        if not home_types & {"Organization", "LocalBusiness", "Corporation", "OnlineStore", "Store"} and not any(t.endswith(("Store", "Business")) for t in home_types):
            out.append(finding("sd.no_organization", C, "No Organization schema on the homepage", Severity.medium,
                               "Organization markup (name, logo, URL, sameAs social profiles, contact) establishes your brand as an entity for Google's Knowledge Graph and AI answer engines.",
                               "Add Organization JSON-LD with name, url, logo, sameAs (Instagram, Facebook, LinkedIn, marketplace listings) and contactPoint.",
                               [(home.url, {"types_found": sorted(home_types)})], site_level=True, effort=1))

    deep = [p for p in pages if p.depth >= 2]
    if deep and not any("BreadcrumbList" in _types(i) for p in pages for i in p.json_ld):
        out.append(finding("sd.no_breadcrumbs", C, "No BreadcrumbList markup", Severity.low,
                           "Breadcrumb markup replaces the raw URL in search results with a readable path and clarifies site hierarchy.",
                           "Add BreadcrumbList JSON-LD to category, product and article templates.",
                           [(p.url, {"depth": p.depth}) for p in deep], effort=1))
    return out
