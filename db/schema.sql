-- ============================================================
-- AI Content Automation — Database Schema
-- Works on Postgres / Supabase. If using Airtable instead, mirror
-- these as bases/tables with matching field names.
-- ============================================================

-- STEP 1: raw + scored trend signals across all 21 opportunity categories
CREATE TABLE IF NOT EXISTS trend_topics (
    id                  BIGSERIAL PRIMARY KEY,
    run_id              TEXT NOT NULL,
    title               TEXT NOT NULL,
    category            TEXT NOT NULL, -- e.g. Freelancing, AI Tools, SaaS, Side Hustles...
    source              TEXT NOT NULL CHECK (source IN ('google_trends','reddit','product_hunt','hacker_news','github_trending','x_twitter','linkedin','medium','indie_hackers','youtube','news','other')),
    window              TEXT NOT NULL CHECK (window IN ('24h','7d','30d')),
    demand_score        NUMERIC(5,2),
    profitability_score NUMERIC(5,2),
    difficulty_score    NUMERIC(5,2),
    competition_score   NUMERIC(5,2),
    seo_score           NUMERIC(5,2),
    viral_score         NUMERIC(5,2),
    automation_score    NUMERIC(5,2),
    longterm_score      NUMERIC(5,2),
    overall_score       NUMERIC(6,2) NOT NULL,
    status              TEXT NOT NULL DEFAULT 'candidate' CHECK (status IN ('candidate','used','rejected')),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_trend_topics_score ON trend_topics (overall_score DESC);
CREATE INDEX IF NOT EXISTS idx_trend_topics_run ON trend_topics (run_id);
CREATE INDEX IF NOT EXISTS idx_trend_topics_category ON trend_topics (category);

-- STEP 2: digital products research
CREATE TABLE IF NOT EXISTS digital_products (
    id                     BIGSERIAL PRIMARY KEY,
    run_id                 TEXT NOT NULL,
    product_name           TEXT NOT NULL,
    product_type           TEXT NOT NULL, -- Notion Template, Canva Template, eBook, AI Agent, SaaS, Chrome Extension...
    description            TEXT,
    target_audience        TEXT,
    difficulty_level       TEXT CHECK (difficulty_level IN ('beginner','intermediate','advanced')),
    estimated_price_usd    NUMERIC(8,2),
    market_demand          TEXT,
    competition_level      TEXT,
    monthly_income_low_usd NUMERIC(10,2),
    monthly_income_high_usd NUMERIC(10,2),
    best_platform          TEXT,
    marketing_strategy     TEXT,
    demand_score           NUMERIC(5,2),
    profitability_score    NUMERIC(5,2),
    difficulty_score       NUMERIC(5,2),
    competition_score      NUMERIC(5,2),
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_digital_products_run ON digital_products (run_id);

-- STEP 3: freelancing opportunities
CREATE TABLE IF NOT EXISTS freelancing_opportunities (
    id                  BIGSERIAL PRIMARY KEY,
    run_id              TEXT NOT NULL,
    skill_required       TEXT NOT NULL,
    niche_type          TEXT CHECK (niche_type IN ('high_paying','low_competition','trending','beginner_friendly','ai_powered')),
    income_potential     TEXT,
    best_platform        TEXT,
    demand_level         TEXT,
    learning_resources   TEXT,
    portfolio_ideas      TEXT,
    how_to_get_clients   TEXT,
    average_pricing      TEXT,
    demand_score         NUMERIC(5,2),
    profitability_score  NUMERIC(5,2),
    competition_score    NUMERIC(5,2),
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_freelancing_run ON freelancing_opportunities (run_id);

-- STEP 4: generated content, one row per content type per run
CREATE TABLE IF NOT EXISTS blog_posts (
    id               BIGSERIAL PRIMARY KEY,
    run_id           TEXT NOT NULL,
    topic_id         BIGINT REFERENCES trend_topics(id),
    title            TEXT NOT NULL,
    meta_description TEXT,
    seo_keywords     TEXT[],
    introduction     TEXT,
    main_content     TEXT NOT NULL,
    conclusion       TEXT,
    faqs             JSONB,
    word_count       INT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS social_content (
    id                  BIGSERIAL PRIMARY KEY,
    run_id              TEXT NOT NULL,
    blog_post_id        BIGINT REFERENCES blog_posts(id),
    twitter_thread       TEXT,
    linkedin_post        TEXT,
    instagram_caption    TEXT,
    facebook_post        TEXT,
    telegram_post        TEXT,
    whatsapp_broadcast   TEXT,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS youtube_content (
    id             BIGSERIAL PRIMARY KEY,
    run_id         TEXT NOT NULL,
    blog_post_id   BIGINT REFERENCES blog_posts(id),
    video_title    TEXT NOT NULL,
    thumbnail_idea TEXT,
    script         TEXT NOT NULL,
    description    TEXT,
    tags           TEXT[],
    hashtags       TEXT[],
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS newsletters (
    id                BIGSERIAL PRIMARY KEY,
    run_id            TEXT NOT NULL,
    weekly_trends     TEXT,
    market_insights   TEXT,
    opportunities     TEXT,
    actionable_tips   TEXT,
    recommended_tools TEXT,
    business_ideas    TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- STEP 5: AI business ideas (10/day)
CREATE TABLE IF NOT EXISTS ai_business_ideas (
    id                        BIGSERIAL PRIMARY KEY,
    run_id                    TEXT NOT NULL,
    idea_name                 TEXT NOT NULL,
    problem                   TEXT NOT NULL,
    solution                  TEXT NOT NULL,
    target_users              TEXT,
    revenue_model             TEXT,
    estimated_dev_cost_usd    NUMERIC(10,2),
    market_size               TEXT,
    monthly_revenue_potential_usd NUMERIC(10,2),
    mvp_features              TEXT[],
    ai_features               TEXT[],
    monetization_strategy     TEXT,
    demand_score              NUMERIC(5,2),
    profitability_score       NUMERIC(5,2),
    difficulty_score          NUMERIC(5,2),
    automation_score          NUMERIC(5,2),
    created_at                TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_ai_business_ideas_run ON ai_business_ideas (run_id);

-- STEP 6: student opportunities
CREATE TABLE IF NOT EXISTS student_opportunities (
    id               BIGSERIAL PRIMARY KEY,
    run_id           TEXT NOT NULL,
    opportunity_name TEXT NOT NULL,
    opportunity_type TEXT CHECK (opportunity_type IN ('online_earning','internship','digital_product','ai_tool','freelancing','remote_job')),
    skill_level      TEXT CHECK (skill_level IN ('beginner','intermediate','advanced')),
    expected_income  TEXT,
    time_required    TEXT,
    platforms        TEXT,
    resources        TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_student_opps_run ON student_opportunities (run_id);

-- STEP 7 + 8: viral content / trend detection with full scoring system
CREATE TABLE IF NOT EXISTS viral_trends (
    id                   BIGSERIAL PRIMARY KEY,
    run_id               TEXT NOT NULL,
    trend_name           TEXT NOT NULL,
    trend_category       TEXT, -- business, ai, startup, digital_product, social_media
    virality_score       NUMERIC(5,2),
    growth_potential     TEXT,
    competition_score    NUMERIC(5,2),
    revenue_potential    TEXT,
    demand_score         NUMERIC(5,2),
    profitability_score  NUMERIC(5,2),
    difficulty_score     NUMERIC(5,2),
    seo_score            NUMERIC(5,2),
    automation_score     NUMERIC(5,2),
    longterm_score       NUMERIC(5,2),
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_viral_trends_run ON viral_trends (run_id);

-- STEP 9: assembled daily report
CREATE TABLE IF NOT EXISTS daily_reports (
    id                          BIGSERIAL PRIMARY KEY,
    run_id                      TEXT NOT NULL UNIQUE,
    report_date                 DATE NOT NULL DEFAULT CURRENT_DATE,
    top_opportunities           JSONB,
    top_digital_products        JSONB,
    top_freelancing_niches      JSONB,
    top_ai_tools                JSONB,
    top_startup_ideas           JSONB,
    top_trending_topics         JSONB,
    best_side_hustles           JSONB,
    highest_revenue_opportunity JSONB,
    lowest_competition_opportunity JSONB,
    recommended_action_plan     TEXT,
    markdown_report             TEXT,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- error handling log, shared by every workflow's error trigger
CREATE TABLE IF NOT EXISTS failed_runs (
    id            BIGSERIAL PRIMARY KEY,
    workflow_name TEXT NOT NULL,
    failed_node   TEXT,
    error_message TEXT,
    payload       JSONB,
    resolved      BOOLEAN DEFAULT false,
    occurred_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_failed_runs_resolved ON failed_runs (resolved);
