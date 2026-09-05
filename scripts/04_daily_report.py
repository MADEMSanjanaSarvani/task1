"""Workflow 04 - Daily Report & Multi-Destination Sync (Steps 9-10)."""
import json
import logging
import os

from common import db, llm
from common.sync_destinations import sync_airtable, sync_google_sheets, sync_notion
from common.util import run_main, today

log = logging.getLogger("04_daily_report")

ACTION_PLAN_SYSTEM_PROMPT = (
    "You are a Digital Product Consultant writing the closing section of a daily "
    "opportunities report. Write a concise, prioritized, actionable 'Recommended "
    "Action Plan' (150-250 words) telling the reader exactly what to do today, this "
    "week, and this month, based on the highest demand + lowest competition + highest "
    "monetization opportunities provided. Plain text, no JSON."
)


def gather_report_data(conn) -> dict:
    q = lambda sql, params=None: db.select_rows(conn, sql, params)  # noqa: E731
    # the run_id must identify *this* run, not whichever historical topic has
    # the highest overall_score of all time (which never changes day to day,
    # and previously caused daily_reports' unique constraint on run_id to
    # collide every time the same all-time-top topic won that ordering again).
    latest_run = q("SELECT run_id FROM trend_topics ORDER BY created_at DESC LIMIT 1")
    top_opportunities = q("SELECT * FROM trend_topics ORDER BY overall_score DESC LIMIT 10")
    top_digital_products = q("SELECT * FROM digital_products ORDER BY profitability_score DESC LIMIT 10")
    top_freelancing_niches = q("SELECT * FROM freelancing_opportunities ORDER BY profitability_score DESC LIMIT 10")
    top_ai_tools = q("SELECT * FROM trend_topics WHERE category = 'AI Tools' ORDER BY overall_score DESC LIMIT 10")
    top_startup_ideas = q("SELECT * FROM ai_business_ideas ORDER BY profitability_score DESC LIMIT 10")
    top_trending_topics = q("SELECT * FROM viral_trends ORDER BY virality_score DESC LIMIT 10")
    best_side_hustles = q("SELECT * FROM trend_topics WHERE category = 'Side Hustles' ORDER BY overall_score DESC LIMIT 10")
    highest_revenue = q("SELECT * FROM ai_business_ideas ORDER BY monthly_revenue_potential_usd DESC LIMIT 1")
    lowest_competition = q("SELECT * FROM trend_topics ORDER BY competition_score ASC LIMIT 1")
    latest_blog = q("SELECT * FROM blog_posts ORDER BY id DESC LIMIT 1")
    latest_social = q("SELECT * FROM social_content ORDER BY id DESC LIMIT 1")
    latest_newsletter = q("SELECT * FROM newsletters ORDER BY id DESC LIMIT 1")

    if not top_opportunities:
        raise RuntimeError("No trend_topics rows found - run 01_trend_research.py first")

    return {
        "run_id": latest_run[0]["run_id"],
        "report_date": today(),
        "top_opportunities": top_opportunities,
        "top_digital_products": top_digital_products,
        "top_freelancing_niches": top_freelancing_niches,
        "top_ai_tools": top_ai_tools,
        "top_startup_ideas": top_startup_ideas,
        "top_trending_topics": top_trending_topics,
        "best_side_hustles": best_side_hustles,
        "highest_revenue_opportunity": highest_revenue[0] if highest_revenue else {},
        "lowest_competition_opportunity": lowest_competition[0] if lowest_competition else {},
        "latest_blog": latest_blog[0] if latest_blog else {},
        "latest_social": latest_social[0] if latest_social else {},
        "latest_newsletter": latest_newsletter[0] if latest_newsletter else {},
    }


def _bullets(items, fmt) -> str:
    return "\n".join(f"{i + 1}. {fmt(x)}" for i, x in enumerate(items)) or "_none_"


def _fmt_opportunity(o):
    return f"**{o['title']}** ({o['category']}) — score {o['overall_score']}"


def _fmt_product(p):
    return f"**{p['product_name']}** — ${p['estimated_price_usd']}, {p['best_platform']}"


def _fmt_freelancing(f):
    return f"**{f['skill_required']}** — {f['income_potential']} on {f['best_platform']}"


def _fmt_title_only(t):
    return f"**{t['title']}**"


def _fmt_startup(s):
    return f"**{s['idea_name']}** — {s['solution']}"


def _fmt_trend(t):
    return f"**{t['trend_name']}** — virality {t['virality_score']}"


def build_markdown(r: dict) -> str:
    highest = r["highest_revenue_opportunity"]
    lowest = r["lowest_competition_opportunity"]
    sections = [
        f"# Daily AI Content & Opportunity Report — {r['report_date']}",
        f"## 1. Top 10 Opportunities\n{_bullets(r['top_opportunities'], _fmt_opportunity)}",
        f"## 2. Top 10 Digital Products\n{_bullets(r['top_digital_products'], _fmt_product)}",
        f"## 3. Top 10 Freelancing Niches\n{_bullets(r['top_freelancing_niches'], _fmt_freelancing)}",
        f"## 4. Top AI Tools\n{_bullets(r['top_ai_tools'], _fmt_title_only)}",
        f"## 5. Top Startup Ideas\n{_bullets(r['top_startup_ideas'], _fmt_startup)}",
        f"## 6. Top Trending Topics\n{_bullets(r['top_trending_topics'], _fmt_trend)}",
        f"## 7. Best Side Hustles\n{_bullets(r['best_side_hustles'], _fmt_title_only)}",
        f"## 8. Highest Revenue Opportunity\n**{highest.get('idea_name', 'N/A')}** — "
        f"up to ${highest.get('monthly_revenue_potential_usd', 0)}/mo",
        f"## 9. Lowest Competition Opportunity\n**{lowest.get('title', 'N/A')}** — "
        f"competition score {lowest.get('competition_score', 'N/A')}",
        f"## 10. Recommended Action Plan\n{r['recommended_action_plan']}",
    ]
    return "\n\n".join(sections) + "\n"


@run_main("04-daily-report")
def main(conn):
    report = gather_report_data(conn)
    log.info("Gathered report data for run_id=%s", report["run_id"])

    plan_text = _generate_action_plan(report)
    report["recommended_action_plan"] = plan_text
    report["markdown_report"] = build_markdown(report)

    db.execute(
        conn,
        """INSERT INTO daily_reports
           (run_id, report_date, top_opportunities, top_digital_products, top_freelancing_niches,
            top_ai_tools, top_startup_ideas, top_trending_topics, best_side_hustles,
            highest_revenue_opportunity, lowest_competition_opportunity, recommended_action_plan,
            markdown_report)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (
            report["run_id"], report["report_date"],
            json.dumps(report["top_opportunities"], default=db.json_default),
            json.dumps(report["top_digital_products"], default=db.json_default),
            json.dumps(report["top_freelancing_niches"], default=db.json_default),
            json.dumps(report["top_ai_tools"], default=db.json_default),
            json.dumps(report["top_startup_ideas"], default=db.json_default),
            json.dumps(report["top_trending_topics"], default=db.json_default),
            json.dumps(report["best_side_hustles"], default=db.json_default),
            json.dumps(report["highest_revenue_opportunity"], default=db.json_default),
            json.dumps(report["lowest_competition_opportunity"], default=db.json_default),
            report["recommended_action_plan"],
            report["markdown_report"],
        ),
    )
    log.info("Daily report saved to Postgres")

    output_dir = os.environ.get("OUTPUT_DIR", "output")
    os.makedirs(f"{output_dir}/reports", exist_ok=True)
    with open(f"{output_dir}/reports/{report['run_id']}-daily-report.md", "w") as f:
        f.write(report["markdown_report"])
    with open(f"{output_dir}/json/{report['run_id']}-daily-report.json", "w") as f:
        os.makedirs(f"{output_dir}/json", exist_ok=True)
        json.dump(report, f, indent=2, default=str)
    log.info("Report files written")

    # Multi-destination sync - each call is best-effort (see sync_destinations.py).
    sync_google_sheets(report["top_opportunities"], "TrendTopics")
    sync_google_sheets(report["top_digital_products"], "DigitalProducts")
    sync_google_sheets(report["top_freelancing_niches"], "Freelancing")
    sync_google_sheets(report["top_startup_ideas"], "AIBusinessIdeas")
    if report["latest_blog"]:
        sync_google_sheets([report["latest_blog"]], "Blogs")
    if report["latest_social"]:
        sync_google_sheets([report["latest_social"]], "SocialMediaPosts")
    if report["latest_newsletter"]:
        sync_google_sheets([report["latest_newsletter"]], "Newsletters")
    sync_google_sheets([{
        "run_id": report["run_id"], "report_date": report["report_date"],
        "recommended_action_plan": report["recommended_action_plan"],
    }], "DailyReports")

    sync_airtable(report["top_opportunities"], "TrendTopics")
    sync_airtable(report["top_digital_products"], "DigitalProducts")
    sync_airtable(report["top_freelancing_niches"], "Freelancing")
    sync_airtable(report["top_startup_ideas"], "AIBusinessIdeas")
    sync_airtable([{
        "run_id": report["run_id"], "report_date": report["report_date"],
        "recommended_action_plan": report["recommended_action_plan"],
    }], "DailyReports")

    for t in report["top_opportunities"]:
        sync_notion(t["title"], "NOTION_DATABASE_ID_TRENDS")
    for p in report["top_digital_products"]:
        sync_notion(p["product_name"], "NOTION_DATABASE_ID_PRODUCTS")
    if report["latest_blog"]:
        sync_notion(report["latest_blog"].get("title", "Untitled"), "NOTION_DATABASE_ID_CONTENT")
    sync_notion(f"Daily Report {report['report_date']}", "NOTION_DATABASE_ID_REPORTS")

    log.info("Multi-destination sync complete")


def _generate_action_plan(report: dict) -> str:
    top5 = [o["title"] for o in report["top_opportunities"][:5]]
    user_prompt = (
        f"Top opportunities: {top5}\n"
        f"Highest revenue idea: {report['highest_revenue_opportunity'].get('idea_name', 'N/A')}\n"
        f"Lowest competition opportunity: {report['lowest_competition_opportunity'].get('title', 'N/A')}"
    )
    return llm.generate_text(ACTION_PLAN_SYSTEM_PROMPT, user_prompt, temperature=0.5)


if __name__ == "__main__":
    main()
