"""Workflow 05 - YouTube Shorts Pipeline (3x/day, $0 stack).

Picks the next unused trend_topics candidate, writes + fact-checks a short
caption-only script, sources stock footage per scene (Pexels, Pixabay fallback),
assembles the video with FFmpeg, mixes in royalty-free music, QCs the render,
uploads to YouTube, and cleans up. Run 3x/day via cron in the GitHub Actions
workflow - each run consumes one topic, so 3 runs/day == 3 different videos.
"""
import datetime
import logging
import os
import shutil
import tempfile

import requests

from common import db, gemini, video
from common.notify import notify_discord
from common.util import run_main
from common.youtube import set_thumbnail, upload_video

log = logging.getLogger("05_youtube_shorts")

SCRIPT_SYSTEM_PROMPT = (
    "You are an expert short-form scriptwriter for a YouTube Shorts channel about AI "
    "tools, freelancing, side hustles, digital products, and online business "
    "opportunities. The video will be CAPTION-ONLY (on-screen text synced to "
    "background music, no voiceover), so write for READING not listening. Always "
    'return strict JSON with keys: title, hook, curiosity_gap, main_explanation, cta, '
    "full_script, keywords (array), hashtags (array), description. Rules: full_script "
    "must be 6-10 short punchy sentences (each becomes a single on-screen caption "
    "card, so keep each sentence under 12 words), factually accurate (no invented "
    "income guarantees or unverifiable stats), strong opening hook, cta points "
    "viewers to 'link in bio' for the full breakdown, no copyrighted quotes."
)

FACT_CHECK_SYSTEM_PROMPT = (
    "You are a rigorous fact-checking model for business/finance content. Verify "
    "every factual claim, income figure, and platform reference in the script. "
    'Return strict JSON: {"confidence": 0-100, "issues": [string], "verdict": '
    '"pass"|"fail"}. Penalize unverifiable income guarantees heavily.'
)

REWRITE_SYSTEM_PROMPT = (
    "Rewrite the script to fix the factual issues listed while preserving format "
    "and length. Return the same JSON schema as before: title, hook, curiosity_gap, "
    "main_explanation, cta, full_script, keywords, hashtags, description."
)

SEO_SYSTEM_PROMPT = (
    'Generate YouTube Shorts SEO metadata. Return strict JSON: {"seo_title": string, '
    '"description": string, "tags": [string], "hashtags": [string]}. Title under 100 '
    "chars, hook-driven, includes #Shorts."
)

CONFIDENCE_THRESHOLD = 90
MAX_REWRITE_ATTEMPTS = 3


class FactCheckFailed(Exception):
    """Distinct from a bug/API failure - this is an expected content-quality gate
    outcome, so main() catches it separately and reports 'needs manual review'
    instead of treating the run as broken."""


def get_next_candidate(conn) -> dict | None:
    rows = db.select_rows(
        conn,
        "SELECT * FROM trend_topics WHERE status = 'candidate' ORDER BY overall_score DESC LIMIT 1",
    )
    return rows[0] if rows else None


def mark_used(conn, topic_id: int):
    db.execute(conn, "UPDATE trend_topics SET status = 'used' WHERE id = %s", (topic_id,))


def reviewed_video_count(conn) -> int:
    rows = db.select_rows(
        conn, "SELECT COUNT(*) AS n FROM published_videos WHERE status IN ('scheduled', 'published')"
    )
    return rows[0]["n"] if rows else 0


def write_script_with_fact_check(topic: dict) -> dict:
    script = gemini.generate_json(
        SCRIPT_SYSTEM_PROMPT,
        f"Topic: {topic['title']}\nCategory: {topic['category']}\n"
        f"Why it matters (scores): demand {topic['demand_score']}, "
        f"profitability {topic['profitability_score']}, competition {topic['competition_score']}.\n"
        "Write the short script now.",
        temperature=0.7,
    )

    rewrite_count = 0
    while True:
        fact_check = gemini.generate_json(
            FACT_CHECK_SYSTEM_PROMPT,
            f"Fact-check this script:\n\n{script['full_script']}",
            temperature=0,
        )
        if fact_check.get("confidence", 0) >= CONFIDENCE_THRESHOLD:
            script["fact_check"] = fact_check
            script["rewrite_count"] = rewrite_count
            return script
        if rewrite_count >= MAX_REWRITE_ATTEMPTS:
            raise FactCheckFailed(
                f"Script failed fact-check {MAX_REWRITE_ATTEMPTS}x for topic_id={topic['id']} "
                f"(last confidence={fact_check.get('confidence')}, issues={fact_check.get('issues')})"
            )
        script = gemini.generate_json(
            REWRITE_SYSTEM_PROMPT,
            f"Original script: {script['full_script']}\nIssues to fix: {', '.join(fact_check.get('issues', []))}",
            temperature=0.5,
        )
        rewrite_count += 1


def search_pexels(query: str) -> str | None:
    api_key = os.environ.get("PEXELS_API_KEY")
    if not api_key:
        return None
    try:
        resp = requests.get(
            "https://api.pexels.com/videos/search",
            params={"query": query, "orientation": "portrait", "per_page": 1},
            headers={"Authorization": api_key},
            timeout=15,
        )
        resp.raise_for_status()
        videos = resp.json().get("videos", [])
        if not videos:
            return None
        files = videos[0].get("video_files", [])
        hd = next((f for f in files if f.get("quality") == "hd"), None)
        return (hd or files[0])["link"] if files else None
    except (requests.RequestException, KeyError, IndexError) as e:
        log.warning("Pexels search failed for %r: %s", query, e)
        return None


def search_pixabay(query: str) -> str | None:
    api_key = os.environ.get("PIXABAY_API_KEY")
    if not api_key:
        return None
    try:
        resp = requests.get(
            "https://pixabay.com/api/videos/",
            params={"key": api_key, "q": query, "per_page": 3},
            timeout=15,
        )
        resp.raise_for_status()
        hits = resp.json().get("hits", [])
        if not hits:
            return None
        videos = hits[0].get("videos", {})
        for quality in ("medium", "large", "small", "tiny"):
            if quality in videos:
                return videos[quality]["url"]
        return None
    except (requests.RequestException, KeyError, IndexError) as e:
        log.warning("Pixabay search failed for %r: %s", query, e)
        return None


def download_file(url: str, dest_path: str):
    resp = requests.get(url, timeout=60, stream=True)
    resp.raise_for_status()
    with open(dest_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=1 << 16):
            f.write(chunk)


def build_video(scenes: list[dict], render_dir: str) -> str:
    """Downloads stock footage per scene, processes each with FFmpeg, concatenates,
    and mixes in background music. Returns the path to the final (pre-QC) video."""
    processed_paths = []
    for scene in scenes:
        clip_url = search_pexels(scene["search_query"]) or search_pixabay(scene["search_query"])
        if not clip_url:
            raise RuntimeError(f"No stock footage found for scene {scene['index']} (query={scene['search_query']!r})")

        raw_path = os.path.join(render_dir, f"scene_{scene['index']}_raw.mp4")
        caption_path = os.path.join(render_dir, f"scene_{scene['index']}_caption.txt")
        processed_path = os.path.join(render_dir, f"scene_{scene['index']}_processed.mp4")

        download_file(clip_url, raw_path)
        with open(caption_path, "w") as f:
            f.write(scene["text"])

        font_path = os.environ.get("RENDER_FONT_PATH", video.FONT_PATH_DEFAULT)
        video.process_scene(raw_path, caption_path, processed_path, scene["duration"], font_path)
        processed_paths.append(processed_path)

    list_path = os.path.join(render_dir, "concat_list.txt")
    with open(list_path, "w") as f:
        for p in processed_paths:
            f.write(f"file '{os.path.basename(p)}'\n")
    novoice_path = os.path.join(render_dir, "novoice.mp4")
    video.concat_scenes(list_path, novoice_path)

    music_path = os.path.join(render_dir, "music.mp3")
    download_file(os.environ["BG_MUSIC_URL"], music_path)
    final_path = os.path.join(render_dir, "final.mp4")
    video.mix_music(novoice_path, music_path, final_path)
    return final_path


@run_main("05-youtube-shorts")
def main(conn):
    topic = get_next_candidate(conn)
    if not topic:
        log.warning("No candidate topics available - skipping this run (has 01_trend_research.py run yet today?)")
        return
    mark_used(conn, topic["id"])
    log.info("Selected topic %r (id=%s)", topic["title"], topic["id"])

    try:
        script = write_script_with_fact_check(topic)
    except FactCheckFailed as e:
        notify_discord(f"⚠️ Shorts script failed fact-check 3x for topic_id {topic['id']}. Routed to manual review instead of publishing.\n{e}")
        log.warning("Fact-check exhausted: %s", e)
        return
    log.info("Script ready after %d rewrite(s), confidence=%s", script["rewrite_count"], script["fact_check"]["confidence"])

    scenes = video.build_scenes(script["full_script"])
    log.info("Split into %d scenes", len(scenes))

    run_id = video.safe_run_id(f"{topic['run_id']}-{topic['id']}")
    render_dir = os.path.join(tempfile.gettempdir(), "shorts-render", run_id)
    os.makedirs(render_dir, exist_ok=True)
    try:
        final_path = build_video(scenes, render_dir)
        duration = video.probe_duration(final_path)
        qc_passed = 15 <= duration <= 62
        if not qc_passed:
            notify_discord(f"⚠️ Shorts QC failed for '{script['title']}': duration {duration:.1f}s out of range. Not published.")
            log.warning("QC failed: duration=%.1fs", duration)
            return

        title_path = os.path.join(render_dir, "title.txt")
        with open(title_path, "w") as f:
            f.write(script["title"])
        thumb_path = os.path.join(render_dir, "thumb.jpg")
        font_path = os.environ.get("RENDER_FONT_PATH", video.FONT_PATH_DEFAULT)
        video.extract_thumbnail(final_path, title_path, thumb_path, font_path)

        seo = gemini.generate_json(
            SEO_SYSTEM_PROMPT,
            f"Script title: {script['title']}\nScript: {script['full_script']}",
            temperature=0.6,
        )

        # The first SHORTS_MANUAL_REVIEW_COUNT videos are uploaded PRIVATE with a
        # scheduled publishAt - a review window to watch each one in YouTube Studio
        # before it goes live (edit its privacy back to Private there to cancel it).
        # After that count is reached, later Shorts publish straight to public -
        # no code change needed to flip back, just adjust the count/hours variables.
        manual_review_count = int(os.environ.get("SHORTS_MANUAL_REVIEW_COUNT", "5"))
        review_buffer_hours = float(os.environ.get("SHORTS_REVIEW_BUFFER_HOURS", "24"))
        needs_review = reviewed_video_count(conn) < manual_review_count

        if needs_review:
            publish_at_dt = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=review_buffer_hours)
            publish_at = publish_at_dt.isoformat()
        else:
            publish_at_dt = datetime.datetime.now(datetime.timezone.utc)
            publish_at = None

        video_id = upload_video(final_path, seo["seo_title"], seo.get("description", ""), seo.get("tags", []), publish_at)
        set_thumbnail(video_id, thumb_path)
        log.info("Uploaded to YouTube: video_id=%s publish_at=%s", video_id, publish_at)

        db.insert_rows(conn, "published_videos", [{
            "run_id": topic["run_id"], "topic_id": topic["id"], "youtube_video_id": video_id,
            "title": script["title"], "script": script["full_script"],
            "fact_check_confidence": script["fact_check"]["confidence"], "rewrite_count": script["rewrite_count"],
            "thumbnail_status": "set", "video_url": f"https://youtube.com/shorts/{video_id}",
            "duration_seconds": duration, "status": "scheduled" if needs_review else "published",
            "published_at": publish_at_dt,
        }])

        if needs_review:
            notify_discord(
                f"🎬 New Short rendered: **{script['title']}**\n"
                f"Preview it (private): https://studio.youtube.com/video/{video_id}/edit\n"
                f"It auto-publishes at {publish_at} unless you edit its privacy back to "
                "Private in Studio before then. Want different music? Download it from "
                "Studio, remix locally, then re-upload as a fresh video and delete this one."
            )
        else:
            notify_discord(f"✅ Published: {script['title']}\nhttps://youtube.com/shorts/{video_id}")
    finally:
        shutil.rmtree(render_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
