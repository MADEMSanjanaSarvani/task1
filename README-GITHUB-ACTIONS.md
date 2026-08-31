# AI Content Automation — GitHub Actions Edition

This is the same pipeline as the n8n version documented in `README.md` (trend
research → digital products/freelancing research → blog/social/YouTube/newsletter
content → AI business ideas/student opportunities/viral detection → daily report
→ 3 YouTube Shorts/day), rebuilt to run as **real Python scripts on GitHub Actions'
own schedule**, instead of as n8n workflow JSON on a self-hosted server.

**Why this exists as a separate implementation, not a replacement**: the two
approaches have real trade-offs — n8n gives you a visual editor and one always-on
server; GitHub Actions gives you no server to maintain and free compute, at the
cost of ephemeral runners (nothing persists between runs) and no visual editor.
Both `workflows/*.json` (n8n) and `scripts/` + `.github/workflows/*.yml` (this)
implement the same pipeline logic independently — pick one, you don't need both.

---

## 1. What's different from the n8n version

| | n8n version | This version |
|---|---|---|
| Orchestration | n8n workflow JSON, self-hosted | GitHub Actions YAML + Python scripts |
| Database | Self-hosted Postgres (Docker) | **Supabase** (hosted Postgres, free tier) — GitHub Actions runners are ephemeral, so state has to live somewhere that survives between runs |
| Server | A VM you provision and maintain | None — GitHub's runners |
| LLM | Gemini (same) | Gemini (same) |
| Video assembly | Self-hosted FFmpeg in a Docker container | Self-hosted FFmpeg, pre-installed on `ubuntu-latest` runners (or installed via `apt-get` in the workflow) |
| Shell safety | Sanitized path components interpolated into Execute Command shell strings | `subprocess.run(args_list)` with argument lists — no shell string is ever built, so there's no injection surface to sanitize against in the first place |
| Google Sheets auth | OAuth2 (interactive) | Service Account (non-interactive — required, since nothing can open a browser on a runner) |
| YouTube auth | OAuth2, connected once in n8n's UI | OAuth2 refresh token, generated once locally (`scripts/setup_youtube_oauth.py`) and stored as a secret |
| Schema | `db/schema.sql` | **Same file, unchanged** — just pointed at Supabase instead of a local container |

---

## 2. Architecture

```
.github/workflows/
  daily-content-pipeline.yml   # cron 06:00 UTC daily
  youtube-shorts.yml           # cron 09:00/14:00/19:00 UTC
  tests.yml                    # runs tests/ on every push/PR touching scripts/

tests/                         # pytest coverage for every pure-logic function
  test_scoring.py              # categorization + Step-8 scoring
  test_video.py                # FFmpeg/ffprobe argument-list construction, scene
                                # splitting, run_id sanitization
  test_daily_report.py         # markdown report assembly
  test_gemini.py               # Gemini response-shape extraction
  test_util.py                 # run_id / date formatting

scripts/
  common/
    db.py                # Postgres/Supabase connection + insert/select helpers
    gemini.py            # Gemini generateContent wrapper, JSON mode
    scoring.py           # Step 8 trend categorization + scoring (pure functions)
    sources.py           # the 6 free trend-source fetchers
    sync_destinations.py # Google Sheets / Airtable / Notion sync (best-effort)
    notify.py            # Discord + email alerts, failed_runs logger
    video.py             # FFmpeg/ffprobe wrappers (argument lists, not shell strings)
    youtube.py           # YouTube Data API v3, refresh-token auth
    util.py              # run_id generation, the run_main() error-handling decorator
  01_trend_research.py
  02_content_generation.py
  03_business_student_viral.py
  04_daily_report.py
  05_youtube_shorts.py
  setup_youtube_oauth.py # run ONCE, locally — see section 5
```

`daily-content-pipeline.yml` runs 4 jobs with explicit dependencies (mirroring the
n8n Execute Workflow chain, but as GitHub Actions' native job graph):
`trend-research` → (`content-generation` **and** `business-student-viral`, in
parallel) → `daily-report` (waits for both, since the report needs data from both).

`youtube-shorts.yml` is independent — it reads the next `candidate` topic directly
from `trend_topics` each time it fires, same as the n8n version.

Every script's `main()` is wrapped by `common/util.run_main()`, which mirrors the
n8n Error Handler workflow: on any uncaught exception, it logs to the `failed_runs`
table, posts to Discord, optionally emails, then exits non-zero — which also makes
the GitHub Actions job itself show red, a second independent failure signal beyond
the Discord alert.

---

## 3. Setup

### 3a. Supabase (the database)

1. Create a free project at [supabase.com](https://supabase.com).
2. In the SQL Editor, run `db/schema.sql` (unchanged from the n8n version).
3. Get the connection string: **Project Settings → Database → Connection string**
   (use the "URI" / session-pooler form). Save it as the `SUPABASE_DB_URL` secret.

### 3b. Gemini

Get a free API key at [aistudio.google.com/apikey](https://aistudio.google.com/apikey).
Save it as `GEMINI_API_KEY`.

### 3c. Google Sheets (service account, not OAuth)

GitHub Actions can't do interactive OAuth, so Sheets access uses a service account:

1. In [Google Cloud Console](https://console.cloud.google.com), enable the Google
   Sheets API, then **IAM & Admin → Service Accounts → Create Service Account**.
2. Create a JSON key for it, download it.
3. Share your target Google Sheet with the service account's `client_email` (found
   inside the JSON key file), same as sharing with any other collaborator.
4. Save the **entire JSON file's contents** as the `GOOGLE_SERVICE_ACCOUNT_JSON`
   secret, and the spreadsheet ID (from its URL) as `GOOGLE_SHEETS_SPREADSHEET_ID`.

### 3d. YouTube OAuth (refresh token, generated once locally)

1. Follow README.md section 9 (Google Cloud Console walkthrough) to create a
   YouTube OAuth **Client ID + Client Secret** — that part is identical.
2. **Locally, on your own machine** (not in Actions):
   ```bash
   pip install google-auth-oauthlib
   python scripts/setup_youtube_oauth.py --client-id YOUR_ID --client-secret YOUR_SECRET
   ```
   This opens a browser once, you sign in and approve, and it prints a refresh
   token.
3. Save three secrets: `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`,
   `YOUTUBE_REFRESH_TOKEN`.
4. Same caveat as the n8n version applies: while the OAuth consent screen is in
   "Testing" mode, tokens are still tied to a 7-day-refresh policy unless the app
   is verified — submit for verification if you want this to run for months
   unattended (see README.md section 9, point 6).

### 3e. Everything else — same free services as the n8n version

Reddit, Product Hunt, GitHub, NewsAPI, YouTube Data API, Pexels, Pixabay, Discord,
Airtable, Notion: same signup process as documented in `README.md` sections 3-4
— only *where you paste the key* changes (a GitHub secret instead of `.env`).

### 3f. Add secrets to the repo

**Settings → Secrets and variables → Actions → New repository secret** for each
of the following. (Names match exactly what the workflow YAML files reference.)

| Secret | Required for |
|---|---|
| `SUPABASE_DB_URL` | every script |
| `GEMINI_API_KEY` | every script that generates content |
| `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET` | 01 |
| `PRODUCTHUNT_TOKEN` | 01 |
| `GH_SEARCH_TOKEN` | 01 (a GitHub personal access token for the trending-repos search — **not** the auto-provided Actions token, name it something else to avoid confusion) |
| `NEWSAPI_KEY` | 01 |
| `YOUTUBE_API_KEY` | 01 (YouTube Data API key, for trending videos) |
| `GOOGLE_SERVICE_ACCOUNT_JSON`, `GOOGLE_SHEETS_SPREADSHEET_ID` | 04 |
| `AIRTABLE_BASE_ID`, `AIRTABLE_API_KEY` | 04 |
| `NOTION_TOKEN`, `NOTION_DATABASE_ID_TRENDS`, `NOTION_DATABASE_ID_PRODUCTS`, `NOTION_DATABASE_ID_CONTENT`, `NOTION_DATABASE_ID_REPORTS` | 04 |
| `PEXELS_API_KEY`, `PIXABAY_API_KEY` | 05 |
| `BG_MUSIC_URL` | 05 (a direct link to a royalty-free track — YouTube Audio Library / Pixabay Music / freesound.org) |
| `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`, `YOUTUBE_REFRESH_TOKEN` | 05 |
| `DISCORD_WEBHOOK_URL` | all (alerts) |
| `ALERT_EMAIL`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD` | all, optional (email alerts alongside Discord — skip these 5 if Discord alone is enough) |

Also add one repository **variable** (Settings → Secrets and variables → Actions →
Variables tab, not Secrets): `GEMINI_MODEL` = `gemini-2.0-flash` (or whatever model
you want — this isn't secret, so it's a variable, not a secret).

---

## 4. First run

1. Push this to GitHub (workflows only run from the default branch, or via manual
   dispatch from any branch).
2. Go to **Actions** tab → **Daily Content Pipeline** → **Run workflow** to trigger
   it manually the first time, rather than waiting for the cron. Watch the
   `trend-research` job's logs for each source fetch, then `content-generation`
   and `business-student-viral`, then `daily-report`.
3. Once that's produced at least one `candidate` row in `trend_topics`, manually
   run **YouTube Shorts Pipeline** the same way and **watch it end to end** — this
   is the step to not skip, same as the n8n version's deployment guide says,
   because the FFmpeg command sequence is the one part of this system that was
   never run against a real video file while building it (see the honesty note in
   README.md section 9a — it applies here too, the FFmpeg logic is shared).
4. Once both have run cleanly once, the cron schedules take over.

---

## 4a. Review-before-publish (Shorts)

The first `SHORTS_MANUAL_REVIEW_COUNT` Shorts (default **5**) are uploaded to
YouTube as **Private** with a scheduled `publishAt` (default 24h out, via the
`SHORTS_REVIEW_BUFFER_HOURS` repo variable) instead of going public
immediately. Each of those runs posts a Discord message with a direct YouTube
Studio preview link — watch it there before it goes live, and edit its
privacy back to Private in Studio if you don't want that one to post. Want
different music than the auto-mixed track? Download it from Studio, remix
locally, then upload the remix as a separate video and delete the private one
— YouTube doesn't allow replacing a video's file in place.

Once `SHORTS_MANUAL_REVIEW_COUNT` videos have been scheduled/published, every
Short after that publishes straight to public automatically — no review step,
no code change needed. Both are repo **variables** (Settings → Secrets and
variables → Actions → Variables tab), so you can raise the review count again
later, or shrink `SHORTS_REVIEW_BUFFER_HOURS`, any time.

---

## 5. Notes specific to this implementation

- **Idempotent-ish reruns**: `02_content_generation.py`, `03_business_student_viral.py`,
  and `04_daily_report.py` all just query Postgres for "the current top candidate" /
  "the latest run" rather than requiring a `run_id` to be threaded through GitHub
  Actions job outputs — so you can re-run any individual job from the Actions UI
  without re-running the whole pipeline, and it'll operate on whatever's currently
  in the database.
- **Timeouts**: `youtube-shorts.yml` sets `timeout-minutes: 30` since Shorts
  generation (Gemini calls + stock footage downloads + FFmpeg encoding + upload)
  is the slowest single run in the system. GitHub Actions' default job timeout is
  6 hours, generous enough that this is just a safety net, not a real constraint.
- **Artifacts**: the daily pipeline uploads the blog markdown and report
  files as workflow run artifacts (30-day retention by default) in addition to
  writing them to Postgres — handy for browsing a specific day's output without
  querying the database directly.
- **Rate limits**: same Gemini free-tier considerations as the n8n version
  (README.md section 9a) — nothing here changes that math, just where the calls
  originate from.
- **Cost**: still $0 beyond whatever's already free — GitHub Actions gives
  generous free minutes on public repos (unlimited) and a monthly free allowance
  on private repos; Supabase's free tier (500MB database, generous request
  limits) comfortably covers this workload.
- **Hardening**: both pipeline workflows set `permissions: contents: read`
  (least privilege — nothing here needs to write to the repo) and a
  `concurrency` group with `cancel-in-progress: false`, so a scheduled run
  queues behind a still-running previous one instead of either overlapping
  with it (which could race on `mark_used`/report reads) or getting killed
  mid-upload if the next cron fires while a Short is still rendering.
- **Tests**: `tests/` has pytest coverage for every pure-logic function in this
  system — trend categorization/scoring, FFmpeg argument-list construction,
  scene splitting, `run_id` sanitization, markdown report assembly, and Gemini
  response-shape extraction (23 tests total). `tests.yml` runs them on every
  push/PR touching `scripts/` or `tests/`. Run them yourself with:
  ```bash
  pip install -r requirements.txt pytest
  pytest
  ```
  These are unit tests for logic that doesn't need live infrastructure (no
  network, no database, no ffmpeg binary required) — they don't replace the
  watched first run in section 4, which is the only way to verify the parts
  that *do* need real Postgres/Gemini/FFmpeg/YouTube.
