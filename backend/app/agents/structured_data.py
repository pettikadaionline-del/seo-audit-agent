"""Agent F: structured data (JSON-LD) detection and validation."""
from __future__ import annotations

from typing import Any

from app.agents.base import AuditAgent, html_pages, is_noindex
from app.models import Category, Effort, Issue, PageData, Severity, SiteContext

# Required / recommended properties for Google rich results (simplified subset).
REQUIRED: dict[str, list[str]] = {
    "Product": ["name"],
    "Offer": ["price", "priceCurrency"],
    "Article": ["headline"],
    "BlogPosting": ["headline"],
    "NewsArticle": ["headline"],
    "Organization": ["name", "url"],
    "LocalBusiness": ["name", "address"],
    "BreadcrumbList": ["itemListElement"],
    "FAQPage": ["mainEntity"],
    "Recipe": ["name", "image"],
    "Review": ["reviewRating", "author"],
    "AggregateRating": ["ratingValue"],
    "WebSite": ["name", "url"],
    "Event": ["name", "startDate", "location"],
}
RECOMMENDED: dict[str, list[str]] = {
    "Product": ["image", "description", "offers", "brand", "sku", "aggregateRating"],
    "Article": ["author", "datePublished", "image", "dateModified"],
    "BlogPosting": ["author", "datePublished", "image"],
    "Organization": ["logo", "sameAs", "contactPoint"],
    "LocalBusiness": ["telephone", "openingHours", "geo"],
    "Recipe": ["recipeIngredient", "recipeInstructions", "totalTime"],
}


def iter_entities(node: Any):
    """Yield every typed entity in a JSON-LD tree (handles @graph and nesting)."""
    if isinstance(node, list):
        for n in node:
            yield from iter_entities(n)
    elif isinstance(node, dict):
        if "@type" in node:
            yield node
        for k, v in node.items():
            if k != "@context" and isinstance(v, (dict, list)):
                yield from iter_entities(v)


def types_of(entity: dict) -> list[str]:
    t = entity.get("@type")
    return [x.split("/")[-1] for x in (t if isinstance(t, list) else [t]) if isinstance(x, str)]


class StructuredDataAgent(AuditAgent):
    category = Category.structured_data
    name = "Structured Data"

    def run(self, pages: list[PageData], site: SiteContext) -> list[Issue]:
        out: list[Issue] = []
        ok = [p for p in html_pages(pages) if not is_noindex(p)]
        if not ok:
            return out

        found_types: dict[str, int] = {}
        missing_props: dict[str, set[str]] = {}
        rec_props: dict[str, set[str]] = {}
        missing_urls: list[str] = []
        rec_urls: list[str] = []
        for p in ok:
            for ent in iter_entities(p.json_ld):
                for t in types_of(ent):
                    found_types[t] = found_types.get(t, 0) + 1
                    miss = [f for f in REQUIRED.get(t, []) if f not in ent]
                    if miss:
                        missing_props.setdefault(t, set()).update(miss)
                        missing_urls.append(p.url)
                    rec = [f for f in RECOMMENDED.get(t, []) if f not in ent]
                    if rec:
                        rec_props.setdefault(t, set()).update(rec)
                        rec_urls.append(p.url)
        self.stats = {"types_found": found_types}

        invalid = [p.url for p in ok if p.json_ld_errors]
        if invalid:
            out.append(self.issue("invalid_json", Severity.high, "Invalid JSON-LD markup",
                "Structured data blocks fail to parse, so search engines ignore them entirely.",
                "Fix the JSON syntax (validate with Google's Rich Results Test).", invalid, impact=6, effort=Effort.low,
                errors={p.url: p.json_ld_errors[:2] for p in ok if p.json_ld_errors}))
        if missing_props:
            out.append(self.issue("required_missing", Severity.high, "Structured data missing required properties",
                "Entities lack properties Google requires for rich results, making them ineligible.",
                "Add the missing properties listed in evidence.", missing_urls, impact=6, effort=Effort.low,
                missing={k: sorted(v) for k, v in missing_props.items()}))
        if rec_props:
            out.append(self.issue("recommended_missing", Severity.low, "Structured data missing recommended properties",
                "Recommended properties improve rich result eligibility and appearance (e.g. price, ratings, images).",
                "Add the recommended properties listed in evidence where data is available.", rec_urls, impact=3, effort=Effort.low,
                missing={k: sorted(v) for k, v in rec_props.items()}))

        no_sd = [p.url for p in ok if not p.json_ld and not p.microdata_types]
        if len(no_sd) == len(ok):
            out.append(self.issue("none", Severity.high, "No structured data on the site",
                "No JSON-LD or microdata found. You are missing rich results (stars, price, FAQ, breadcrumbs) and "
                "giving AI/answer engines less machine-readable context.",
                "Start with Organization + WebSite on the homepage, Product on product pages, BreadcrumbList site-wide, Article on blog posts.",
                [site.start_url], impact=7, effort=Effort.medium))
        elif no_sd:
            out.append(self.issue("partial", Severity.low, "Pages without structured data",
                "Some indexable pages have no structured data.", "Add the schema type matching each page template.",
                no_sd, impact=3, effort=Effort.medium))

        home = ok[0]
        home_types = {t for e in iter_entities(home.json_ld) for t in types_of(e)}
        if found_types and not home_types & {"Organization", "LocalBusiness", "Corporation", "Store", "OnlineStore"}:
            out.append(self.issue("organization_missing", Severity.medium, "No Organization schema on homepage",
                "Organization markup establishes your brand entity (logo, social profiles) for the Knowledge Graph and AI engines.",
                "Add Organization (or LocalBusiness) JSON-LD with name, url, logo and sameAs links.",
                [home.url], impact=5, effort=Effort.low))
        product_like = [p.url for p in ok if any(s in p.url for s in ("/product", "/products/", "/shop/", "/item"))]
        has_product = {p.url for p in ok if "Product" in {t for e in iter_entities(p.json_ld) for t in types_of(e)}}
        missing_product = [u for u in product_like if u not in has_product]
        if missing_product:
            out.append(self.issue("product_missing", Severity.high, "Product pages without Product schema",
                "Product URLs lack Product markup, so they can't show price, availability or review stars in Google.",
                "Add Product + Offer (+ AggregateRating if you have reviews) JSON-LD to product templates.",
                missing_product, impact=7, effort=Effort.low))
        if len(ok) > 3 and "BreadcrumbList" not in found_types:
            out.append(self.issue("breadcrumbs_missing", Severity.low, "No BreadcrumbList schema",
                "Breadcrumb markup gives cleaner SERP URLs and clarifies site hierarchy.",
                "Add BreadcrumbList JSON-LD matching visible breadcrumbs.", [site.start_url], impact=3, effort=Effort.low))
        faq_no_schema = [p.url for p in ok if p.has_faq_pattern and "FAQPage" not in {t for e in iter_entities(p.json_ld) for t in types_of(e)}]
        if faq_no_schema:
            out.append(self.issue("faq_unmarked", Severity.info, "FAQ-style content without FAQPage schema",
                "Pages have Q&A content that is not marked up. FAQ markup still helps AI engines extract answers.",
                "Add FAQPage JSON-LD mirroring the visible Q&A.", faq_no_schema, impact=2, effort=Effort.low))
        return out
