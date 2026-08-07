import importlib
import sys


def _load_daily_report_module():
    """04_daily_report.py starts with a digit, so it can't be imported with a
    normal `import` statement - load it by file path instead."""
    import importlib.util
    import os

    path = os.path.join(os.path.dirname(__file__), "..", "scripts", "04_daily_report.py")
    spec = importlib.util.spec_from_file_location("daily_report_module", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_markdown_includes_every_section():
    mod = _load_daily_report_module()
    report = {
        "report_date": "2026-07-27",
        "top_opportunities": [{"title": "AI resume tools", "category": "AI Tools", "overall_score": 88}],
        "top_digital_products": [{"product_name": "Notion CRM", "estimated_price_usd": 19, "best_platform": "Gumroad"}],
        "top_freelancing_niches": [{"skill_required": "Prompt Eng", "income_potential": "$50/hr", "best_platform": "Upwork"}],
        "top_ai_tools": [{"title": "Tool A"}],
        "top_startup_ideas": [{"idea_name": "Startup A", "solution": "Solves X"}],
        "top_trending_topics": [{"trend_name": "Trend A", "virality_score": 90}],
        "best_side_hustles": [{"title": "Hustle A"}],
        "highest_revenue_opportunity": {"idea_name": "Best Idea", "monthly_revenue_potential_usd": 5000},
        "lowest_competition_opportunity": {"title": "Easy Win", "competition_score": 12},
        "recommended_action_plan": "Do X today.",
    }
    md = mod.build_markdown(report)
    for expected in [
        "## 1. Top 10 Opportunities", "AI resume tools",
        "## 2. Top 10 Digital Products", "Notion CRM",
        "## 8. Highest Revenue Opportunity", "Best Idea",
        "## 9. Lowest Competition Opportunity", "Easy Win",
        "## 10. Recommended Action Plan", "Do X today.",
    ]:
        assert expected in md, f"missing {expected!r} in report"


def test_build_markdown_handles_empty_sections_gracefully():
    mod = _load_daily_report_module()
    report = {
        "report_date": "2026-07-27",
        "top_opportunities": [], "top_digital_products": [], "top_freelancing_niches": [],
        "top_ai_tools": [], "top_startup_ideas": [], "top_trending_topics": [], "best_side_hustles": [],
        "highest_revenue_opportunity": {}, "lowest_competition_opportunity": {},
        "recommended_action_plan": "Nothing scored yet.",
    }
    md = mod.build_markdown(report)
    assert "N/A" in md
    assert "_none_" in md
