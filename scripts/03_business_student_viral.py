"""Workflow 03 - AI Business Ideas, Student Opportunities & Viral Detection (Steps 5-7)."""
import logging

from common import db, gemini
from common.util import run_main

log = logging.getLogger("03_business_student_viral")

BUSINESS_IDEAS_SYSTEM_PROMPT = (
    "You are an AI Business Idea Consultant. Generate exactly 10 new AI business ideas "
    'based on the given trending topics. Return strict JSON: {"ideas": [{"idea_name": '
    'string, "problem": string, "solution": string, "target_users": string, '
    '"revenue_model": string, "estimated_dev_cost_usd": number, "market_size": string, '
    '"monthly_revenue_potential_usd": number, "mvp_features": [string], "ai_features": '
    '[string], "monetization_strategy": string, "demand_score": number, '
    '"profitability_score": number, "difficulty_score": number, "automation_score": '
    "number}]}. All *_score fields 0-100. Prioritize high demand, low competition, high "
    "monetization, global market, beginner-friendly execution, and AI automation "
    "possibilities."
)

STUDENT_SYSTEM_PROMPT = (
    "You are a Student Income Opportunities researcher. Based on the trending topics, "
    "find at least 8 opportunities for students: online earning opportunities, "
    "internship ideas, digital product ideas, AI tools for students, freelancing "
    'ideas, and remote jobs. Return strict JSON: {"opportunities": [{"opportunity_name": '
    'string, "opportunity_type": "online_earning"|"internship"|"digital_product"|'
    '"ai_tool"|"freelancing"|"remote_job", "skill_level": "beginner"|"intermediate"|'
    '"advanced", "expected_income": string, "time_required": string, "platforms": '
    'string, "resources": string}]}.'
)

VIRAL_SYSTEM_PROMPT = (
    "You are a Viral Trend Analyst. Detect viral business trends, viral AI trends, "
    "trending startup ideas, trending digital products, and trending social media "
    'topics from the given topics. Return strict JSON: {"trends": [{"trend_name": '
    'string, "trend_category": "business"|"ai"|"startup"|"digital_product"|'
    '"social_media", "virality_score": number, "growth_potential": string, '
    '"competition_score": number, "revenue_potential": string, "demand_score": number, '
    '"profitability_score": number, "difficulty_score": number, "seo_score": number, '
    '"automation_score": number, "longterm_score": number}]}. All numeric score fields '
    "0-100. Return at least 10 trends."
)


def get_top_topics(conn, limit: int = 15) -> list[dict]:
    return db.select_rows(
        conn,
        "SELECT * FROM trend_topics WHERE status = 'candidate' ORDER BY overall_score DESC LIMIT %s",
        (limit,),
    )


@run_main("03-business-student-viral")
def main(conn):
    topics = get_top_topics(conn)
    if not topics:
        raise RuntimeError("No candidate topics available - run 01_trend_research.py first")
    run_id = topics[0]["run_id"]
    topics_summary = [{"title": t["title"], "category": t["category"]} for t in topics]
    log.info("Using %d topics for run_id=%s", len(topics), run_id)

    ideas_response = gemini.generate_json(
        BUSINESS_IDEAS_SYSTEM_PROMPT,
        f"Trending topics:\n{topics_summary}\n\nGenerate 10 fresh, unique AI business ideas now.",
        temperature=0.8,
    )
    ideas = ideas_response.get("ideas", [])
    if len(ideas) < 10:
        raise RuntimeError(f"Expected 10 AI business ideas, got {len(ideas)}")
    for idea in ideas:
        idea["run_id"] = run_id
    db.insert_rows(conn, "ai_business_ideas", ideas)
    log.info("Saved %d AI business ideas", len(ideas))

    student_response = gemini.generate_json(
        STUDENT_SYSTEM_PROMPT,
        f"Trending topics:\n{topics_summary}\n\nGenerate the student opportunities now.",
        temperature=0.7,
    )
    opportunities = student_response.get("opportunities", [])
    for o in opportunities:
        o["run_id"] = run_id
    db.insert_rows(conn, "student_opportunities", opportunities)
    log.info("Saved %d student opportunities", len(opportunities))

    viral_response = gemini.generate_json(
        VIRAL_SYSTEM_PROMPT,
        f"Trending topics:\n{topics_summary}\n\nDetect viral trends now.",
        temperature=0.75,
    )
    trends = viral_response.get("trends", [])
    for t in trends:
        t["run_id"] = run_id
    db.insert_rows(conn, "viral_trends", trends)
    log.info("Saved %d viral trends", len(trends))


if __name__ == "__main__":
    main()
