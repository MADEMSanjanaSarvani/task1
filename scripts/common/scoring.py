"""Trend categorization and STEP-8 scoring logic (ported from the n8n Code node)."""
import math
import re
import random

CATEGORY_KEYWORDS = {
    "Freelancing": r"freelanc|upwork|fiverr|client work|gig",
    "Digital Products": r"template|ebook|notion|canva|prompt pack|digital product|pdf guide",
    "AI Tools": r"\bai\b|gpt|llm|chatbot|copilot|midjourney",
    "Side Hustles": r"side hustle|side gig|extra income",
    "Passive Income Ideas": r"passive income|dividend|royalt",
    "Online Business Ideas": r"online business|ecommerce|dropship",
    "Remote Jobs": r"remote job|work from home|wfh",
    "Tech Trends": r"tech trend|technology|developer|programming",
    "Productivity Tools": r"productivity|notion|todo|time management",
    "Startup Ideas": r"startup|founder|venture|y combinator",
    "SaaS": r"saas|subscription software|micro-saas",
    "Digital Marketing": r"marketing|seo|content marketing|ads|growth hack",
    "No-Code Tools": r"no.?code|low.?code|bubble|webflow|zapier",
    "AI Automation": r"automation|workflow|n8n|zapier|make\.com",
    "Mobile Apps": r"mobile app|ios app|android app|app store",
    "Website Ideas": r"website|landing page|web design",
    "Student Income Opportunities": r"student|college|university|intern",
    "Career Growth": r"career|resume|job interview|promotion",
    "Business Trends": r"business trend|market trend|industry",
    "Government Tech Trends": r"government|gov.?tech|policy|regulation",
    "Viral Internet Trends": r"viral|trending now|meme|going viral",
}

SOURCE_WEIGHT = {
    "reddit": 1.1, "product_hunt": 1.3, "hacker_news": 1.15,
    "github_trending": 1.1, "news": 0.9, "youtube": 1.15,
}
AUTOMATION_BOOST = re.compile(r"AI Tools|No-Code Tools|AI Automation|SaaS|Productivity Tools")
VIRAL_BOOST = re.compile(r"Viral Internet Trends|Side Hustles|Passive Income Ideas")


def categorize(title: str) -> str:
    for cat, pattern in CATEGORY_KEYWORDS.items():
        if re.search(pattern, title, re.IGNORECASE):
            return cat
    return "Tech Trends"


def score_topics(raw_items: list[dict], run_id: str) -> list[dict]:
    """raw_items: list of {title, source, window, signal}. Returns scored+deduped rows."""
    seen = {}
    for t in raw_items:
        title = (t.get("title") or "").strip()
        if len(title) < 6:
            continue
        key = title.lower()[:80]
        category = categorize(title)
        weight = SOURCE_WEIGHT.get(t["source"], 1)
        signal = t.get("signal") or 1
        demand = min(100, round(math.log10(max(signal, 0) + 1) * 28 * weight))
        competition = min(100, max(10, 35 if len(title) > 70 else 65))
        seo = min(100, round(demand * 0.6 + (100 - competition) * 0.4))
        viral = min(100, round(demand * (1.25 if VIRAL_BOOST.search(category) else 0.9)))
        automation = min(100, round((75 if AUTOMATION_BOOST.search(category) else 35) + random.random() * 20))
        difficulty = min(100, max(10, 100 - round(demand * 0.3 + competition * 0.2)))
        profitability = min(100, round(demand * 0.5 + (100 - competition) * 0.3 + seo * 0.2))
        longterm = min(100, round((demand + (100 - competition) + automation) / 3))
        overall = round(
            demand * 0.22 + profitability * 0.2 + (100 - difficulty) * 0.1
            + (100 - competition) * 0.15 + seo * 0.13 + viral * 0.1
            + automation * 0.06 + longterm * 0.04
        )
        row = {
            "run_id": run_id, "title": title[:250], "category": category,
            "source": t["source"], "window": t["window"],
            "demand_score": demand, "profitability_score": profitability,
            "difficulty_score": difficulty, "competition_score": competition,
            "seo_score": seo, "viral_score": viral, "automation_score": automation,
            "longterm_score": longterm, "overall_score": overall, "status": "candidate",
        }
        if key not in seen or seen[key]["overall_score"] < overall:
            seen[key] = row

    ranked = sorted(seen.values(), key=lambda r: r["overall_score"], reverse=True)
    return ranked[:60]


def select_top_topics(scored_rows: list[dict], per_category: int = 2, total: int = 20) -> list[dict]:
    by_category: dict[str, list[dict]] = {}
    for t in sorted(scored_rows, key=lambda r: r["overall_score"], reverse=True):
        bucket = by_category.setdefault(t["category"], [])
        if len(bucket) < per_category:
            bucket.append(t)
    flat = [t for bucket in by_category.values() for t in bucket]
    return flat[:total]
