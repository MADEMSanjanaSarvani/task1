"""Workflow 01 - Trend & Opportunity Research (Steps 1-3).

Fetches trends from 6 free sources, categorizes + scores them (Step 8), saves the
candidate pool, then asks the LLM to research digital products (Step 2) and
freelancing opportunities (Step 3) based on the top-scoring topics.

Run standalone: python scripts/01_trend_research.py
"""
import logging
import os

from common import db, llm, sources, scoring
from common.util import new_run_id, run_main

log = logging.getLogger("01_trend_research")

DIGITAL_PRODUCT_SYSTEM_PROMPT = (
    "You are an expert Digital Product Consultant. Given a list of currently trending "
    "topics, research and propose at least 10 trending digital products spanning "
    "categories like Notion Templates, Canva Templates, Resume Templates, AI Prompt "
    "Packs, eBooks, Study Materials, AI Agents, SaaS Ideas, Chrome Extensions, Mobile "
    "Apps, Productivity Tools, Student Tools, Online Courses, Templates, Web "
    "Components, UI Kits, Design Systems, PDF Guides. Return strict JSON: "
    '{"products": [{"product_name": string, "product_type": string, "description": '
    'string, "target_audience": string, "difficulty_level": "beginner"|"intermediate"'
    '|"advanced", "estimated_price_usd": number, "market_demand": string, '
    '"competition_level": string, "monthly_income_low_usd": number, '
    '"monthly_income_high_usd": number, "best_platform": string, "marketing_strategy": '
    'string, "demand_score": number, "profitability_score": number, "difficulty_score": '
    'number, "competition_score": number}]}. All *_score fields are 0-100. Be factual, '
    "avoid duplicate or outdated ideas, prioritize high demand + low competition + high "
    "monetization."
)

FREELANCING_SYSTEM_PROMPT = (
    "You are an expert Freelancing Mentor. Given trending topics, propose at least 10 "
    "freelancing opportunities covering high-paying niches, low-competition niches, "
    "trending skills, beginner-friendly services, and AI-powered services on platforms "
    "like Upwork, Fiverr, Freelancer, Toptal, Contra, PeoplePerHour, LinkedIn, Guru, and "
    'remote job boards. Return strict JSON: {"opportunities": [{"skill_required": '
    'string, "niche_type": "high_paying"|"low_competition"|"trending"|"beginner_friendly"'
    '|"ai_powered", "income_potential": string, "best_platform": string, '
    '"demand_level": string, "learning_resources": string, "portfolio_ideas": string, '
    '"how_to_get_clients": string, "average_pricing": string, "demand_score": number, '
    '"profitability_score": number, "competition_score": number}]}. All *_score fields '
    "0-100."
)


@run_main("01-trend-research")
def main(conn):
    run_id = new_run_id()
    log.info("Starting trend research run %s", run_id)

    raw_items = sources.fetch_all_sources()
    log.info("Fetched %d raw items from trend sources", len(raw_items))

    scored = scoring.score_topics(raw_items, run_id)
    log.info("Scored %d deduped topics", len(scored))

    saved_ids = db.insert_rows(conn, "trend_topics", scored)
    for row, row_id in zip(scored, saved_ids):
        row["id"] = row_id

    top_topics = scoring.select_top_topics(scored, per_category=2, total=20)
    log.info("Selected %d top topics as research seeds", len(top_topics))

    topics_summary = [{"title": t["title"], "category": t["category"], "overall_score": t["overall_score"]} for t in top_topics]

    products_response = llm.generate_json(
        DIGITAL_PRODUCT_SYSTEM_PROMPT,
        f"Trending topics for {run_id}:\n{topics_summary}\n\nPropose the digital products now.",
        temperature=0.6,
    )
    products = products_response.get("products", [])
    for p in products:
        p["run_id"] = run_id
    db.insert_rows(conn, "digital_products", products)
    log.info("Saved %d digital products", len(products))

    freelancing_response = llm.generate_json(
        FREELANCING_SYSTEM_PROMPT,
        f"Trending topics for {run_id}:\n{topics_summary}\n\nPropose the freelancing opportunities now.",
        temperature=0.6,
    )
    opportunities = freelancing_response.get("opportunities", [])
    for o in opportunities:
        o["run_id"] = run_id
    db.insert_rows(conn, "freelancing_opportunities", opportunities)
    log.info("Saved %d freelancing opportunities", len(opportunities))

    # Exposed as a job output for GitHub Actions (see daily-content-pipeline.yml,
    # which reads this to pass run_id to the jobs that depend on this one). Downstream
    # scripts don't strictly need it - they look up the latest run_id from Postgres -
    # but it's useful for the workflow YAML's log/notification steps.
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a") as f:
            f.write(f"run_id={run_id}\n")
    log.info("run_id=%s", run_id)


if __name__ == "__main__":
    main()
