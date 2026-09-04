"""Workflow 02 - Content Generation (Step 4).

Takes the top-scoring candidate topic and generates a full content package: an
SEO blog (1500+ words), short-form social posts, a YouTube script package, and a
newsletter. Run after 01_trend_research.py (reads the topic straight from Postgres,
so it can also be re-run independently against whatever's currently a 'candidate').
"""
import logging
import os
import re

from common import db, llm
from common.util import run_main

log = logging.getLogger("02_content_generation")

BLOG_SYSTEM_PROMPT = (
    "You are an expert SEO Content Researcher and Blog Writer. Write a factually "
    "accurate, SEO-optimized blog article of at least 1500 words about the given "
    'trending opportunity. Return strict JSON: {"title": string, "meta_description": '
    'string, "seo_keywords": [string], "introduction": string, "main_content": string '
    '(markdown with H2/H3 headers, at least 1200 words), "conclusion": string, "faqs": '
    '[{"question": string, "answer": string}] (at least 5)}. Avoid duplicate or '
    "outdated information, include actionable recommendations, and prioritize "
    "high-value monetizable opportunities."
)

SOCIAL_SYSTEM_PROMPT = (
    "You are a social media copywriter. Repurpose the given blog article into "
    'short-form content. Return strict JSON: {"twitter_thread": string (5-8 numbered '
    'tweets), "linkedin_post": string, "instagram_caption": string (with emojis and '
    'hashtags), "facebook_post": string, "telegram_post": string, "whatsapp_broadcast": '
    "string (short, high-urgency)}."
)

YOUTUBE_SYSTEM_PROMPT = (
    "You are a YouTube content strategist. Turn the blog article into a YouTube video "
    'package. Return strict JSON: {"video_title": string (under 100 chars, hook-driven), '
    '"thumbnail_idea": string, "script": string (full spoken script, 3-6 minutes), '
    '"description": string, "tags": [string], "hashtags": [string]}.'
)

NEWSLETTER_SYSTEM_PROMPT = (
    "You are a newsletter editor for a daily opportunities newsletter. Return strict "
    'JSON: {"weekly_trends": string, "market_insights": string, "opportunities": '
    'string, "actionable_tips": string, "recommended_tools": string, "business_ideas": '
    "string}. Keep each section concise (100-200 words), punchy, and actionable."
)


def get_top_topic(conn) -> dict:
    rows = db.select_rows(
        conn,
        "SELECT * FROM trend_topics WHERE status = 'candidate' ORDER BY overall_score DESC LIMIT 1",
    )
    if not rows:
        raise RuntimeError("No candidate topics available - run 01_trend_research.py first")
    return rows[0]


def word_count(*parts: str) -> int:
    return sum(len(re.findall(r"\S+", p or "")) for p in parts)


@run_main("02-content-generation")
def main(conn):
    topic = get_top_topic(conn)
    run_id = topic["run_id"]
    log.info("Generating content for topic %r (run_id=%s)", topic["title"], run_id)

    blog = llm.generate_json(
        BLOG_SYSTEM_PROMPT,
        f"Write the blog article for this trending opportunity:\n"
        f"Title: {topic['title']}\nCategory: {topic['category']}\n"
        f"Scores: demand {topic['demand_score']}, profitability {topic['profitability_score']}, "
        f"competition {topic['competition_score']}, SEO {topic['seo_score']}",
        temperature=0.7,
    )
    wc = word_count(blog.get("introduction", ""), blog.get("main_content", ""), blog.get("conclusion", ""))
    blog_row = {
        "run_id": run_id, "topic_id": topic["id"], "title": blog["title"],
        "meta_description": blog.get("meta_description", ""), "seo_keywords": blog.get("seo_keywords", []),
        "introduction": blog.get("introduction", ""), "main_content": blog.get("main_content", ""),
        "conclusion": blog.get("conclusion", ""), "faqs": _json(blog.get("faqs", [])), "word_count": wc,
    }
    blog_id = db.insert_rows(conn, "blog_posts", [blog_row])[0]
    log.info("Blog saved (id=%s, %d words)", blog_id, wc)

    output_dir = os.environ.get("OUTPUT_DIR", "output")
    os.makedirs(f"{output_dir}/blogs", exist_ok=True)
    md = (
        f"# {blog['title']}\n\n_{blog.get('meta_description', '')}_\n\n"
        f"{blog.get('introduction', '')}\n\n{blog.get('main_content', '')}\n\n"
        f"{blog.get('conclusion', '')}\n\n## FAQs\n\n"
        + "\n\n".join(f"**{f['question']}**\n{f['answer']}" for f in blog.get("faqs", []))
    )
    with open(f"{output_dir}/blogs/{run_id}-blog.md", "w") as f:
        f.write(md)

    social = llm.generate_json(
        SOCIAL_SYSTEM_PROMPT,
        f"Blog title: {blog['title']}\nIntroduction: {blog.get('introduction', '')}\n"
        f"Key keywords: {', '.join(blog.get('seo_keywords', []))}",
        temperature=0.75,
    )
    social_row = {"run_id": run_id, "blog_post_id": blog_id, **{
        k: social.get(k, "") for k in
        ["twitter_thread", "linkedin_post", "instagram_caption", "facebook_post", "telegram_post", "whatsapp_broadcast"]
    }}
    db.insert_rows(conn, "social_content", [social_row])
    log.info("Social content saved")

    youtube = llm.generate_json(
        YOUTUBE_SYSTEM_PROMPT,
        f"Blog title: {blog['title']}\nMain content summary: {blog.get('introduction', '')}",
        temperature=0.75,
    )
    youtube_row = {
        "run_id": run_id, "blog_post_id": blog_id, "video_title": youtube.get("video_title", ""),
        "thumbnail_idea": youtube.get("thumbnail_idea", ""), "script": youtube.get("script", ""),
        "description": youtube.get("description", ""), "tags": youtube.get("tags", []),
        "hashtags": youtube.get("hashtags", []),
    }
    db.insert_rows(conn, "youtube_content", [youtube_row])
    log.info("YouTube content saved")

    newsletter = llm.generate_json(
        NEWSLETTER_SYSTEM_PROMPT,
        f"Base the newsletter on this run's top opportunity: {topic['title']} (category: {topic['category']}).",
        temperature=0.6,
    )
    newsletter_row = {"run_id": run_id, **{
        k: newsletter.get(k, "") for k in
        ["weekly_trends", "market_insights", "opportunities", "actionable_tips", "recommended_tools", "business_ideas"]
    }}
    db.insert_rows(conn, "newsletters", [newsletter_row])
    log.info("Newsletter saved")


def _json(value):
    import json
    return json.dumps(value)


if __name__ == "__main__":
    main()
