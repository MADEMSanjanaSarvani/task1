from common.scoring import categorize, score_topics, select_top_topics


def test_categorize_matches_known_keywords():
    assert categorize("How I make money freelancing on Upwork") == "Freelancing"
    assert categorize("New AI tool launches today") == "AI Tools"
    assert categorize("This side hustle made me $500") == "Side Hustles"


def test_categorize_falls_back_to_tech_trends():
    assert categorize("Some totally unrelated headline about nothing") == "Tech Trends"


def test_score_topics_scores_are_bounded_and_tagged():
    raw = [
        {"title": "How I make $5000/month freelancing on Upwork", "source": "reddit", "window": "24h", "signal": 150},
        {"title": "New AI automation tool for SaaS founders", "source": "product_hunt", "window": "24h", "signal": 300},
        {"title": "Show HN: my new AI automation tool", "source": "hacker_news", "window": "7d", "signal": 250},
    ]
    scored = score_topics(raw, "run-1")
    assert len(scored) == 3
    for row in scored:
        assert row["run_id"] == "run-1"
        assert row["status"] == "candidate"
        for key in [
            "demand_score", "profitability_score", "difficulty_score", "competition_score",
            "seo_score", "viral_score", "automation_score", "longterm_score", "overall_score",
        ]:
            assert 0 <= row[key] <= 100, f"{key}={row[key]} out of range"


def test_score_topics_dedupes_by_title_keeping_higher_score():
    raw = [
        {"title": "AI Tools For Freelancers", "source": "news", "window": "30d", "signal": 40},
        {"title": "ai tools for freelancers", "source": "product_hunt", "window": "24h", "signal": 500},
    ]
    scored = score_topics(raw, "run-1")
    assert len(scored) == 1
    assert scored[0]["source"] == "product_hunt"  # the higher-signal duplicate wins


def test_score_topics_drops_short_titles():
    raw = [{"title": "Hi", "source": "reddit", "window": "24h", "signal": 100}]
    assert score_topics(raw, "run-1") == []


def test_select_top_topics_caps_per_category_and_total():
    scored = [
        {"category": "AI Tools", "overall_score": 90, "title": "a"},
        {"category": "AI Tools", "overall_score": 80, "title": "b"},
        {"category": "AI Tools", "overall_score": 70, "title": "c"},
        {"category": "Freelancing", "overall_score": 60, "title": "d"},
    ]
    top = select_top_topics(scored, per_category=2, total=20)
    ai_tools_count = sum(1 for t in top if t["category"] == "AI Tools")
    assert ai_tools_count == 2  # capped per category, even though 3 were eligible
    assert len(top) == 3  # 2 AI Tools + 1 Freelancing
