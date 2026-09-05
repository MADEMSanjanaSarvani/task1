"""Workflow 05 - YouTube Shorts Pipeline (1x/day, $0 stack).

Picks the next unused trend_topics candidate, writes + fact-checks a short
Max & Nova dialogue script, synthesizes each line with free TTS, renders each
turn as a two-character "talking heads" scene with FFmpeg, mixes in ducked
royalty-free music under the voices, QCs the render, uploads to YouTube, and
cleans up. The first SHORTS_MANUAL_REVIEW_COUNT videos upload private with a
scheduled publish for review; later ones publish straight to public.
"""
import datetime
import logging
import os
import shutil
import tempfile

import requests

from common import db, llm, tts, video
from common.notify import notify_discord
from common.util import run_main
from common.youtube import set_thumbnail, upload_video

log = logging.getLogger("05_youtube_shorts")

# Committed once, reused by every render - see the repo's assets/characters/
# dir for the portraits themselves. Whoever's speaking gets a pulsing glow
# border (see common/video.py) rather than a mouth animation, so only one
# portrait per character is needed, not a matched pair of expressions.
CHAR_ASSETS_DIR = os.path.join(os.path.dirname(__file__), "..", "assets", "characters")
MAX_PORTRAIT = os.path.join(CHAR_ASSETS_DIR, "max.png")
NOVA_PORTRAIT = os.path.join(CHAR_ASSETS_DIR, "nova.png")

VOICE_BY_SPEAKER = {"Max": tts.MAX_VOICE, "Nova": tts.NOVA_VOICE}

SCRIPT_SYSTEM_PROMPT = (
    "You are an expert short-form scriptwriter for a YouTube Shorts channel about AI "
    "tools, freelancing, side hustles, digital products, and online business "
    "opportunities. The video is a conversation between two recurring animated "
    "hosts, Max and Nova, who take turns explaining the topic to each other and "
    "to the viewer - write natural back-and-forth dialogue, not a monologue. "
    'Always return strict JSON with keys: title, hook, cta, dialogue, keywords '
    '(array), hashtags (array), description. "dialogue" must be an array of 6-10 '
    '{"speaker": "Max"|"Nova", "line": string} turns, alternating speakers, each '
    "line under 18 words (it's spoken aloud AND shown as a caption, so keep it "
    "punchy and natural to say out loud). Rules: factually accurate (no invented "
    "income guarantees or unverifiable stats), Max opens with a strong hook, "
    "Nova's final line is the cta pointing viewers to 'link in bio' for the full "
    "breakdown, no copyrighted quotes."
)

FACT_CHECK_SYSTEM_PROMPT = (
    "You are a rigorous fact-checking model for business/finance content. Verify "
    "every factual claim, income figure, and platform reference in the dialogue. "
    'Return strict JSON: {"confidence": 0-100, "issues": [string], "verdict": '
    '"pass"|"fail"}. Penalize unverifiable income guarantees heavily.'
)

REWRITE_SYSTEM_PROMPT = (
    "Rewrite the dialogue to fix the factual issues listed while preserving the "
    "Max/Nova back-and-forth format and length. Return the same JSON schema as "
    "before: title, hook, cta, dialogue, keywords, hashtags, description."
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


def dialogue_transcript(dialogue: list[dict]) -> str:
    return "\n".join(f"{t['speaker']}: {t['line']}" for t in dialogue)


def write_script_with_fact_check(topic: dict) -> dict:
    script = llm.generate_json(
        SCRIPT_SYSTEM_PROMPT,
        f"Topic: {topic['title']}\nCategory: {topic['category']}\n"
        f"Why it matters (scores): demand {topic['demand_score']}, "
        f"profitability {topic['profitability_score']}, competition {topic['competition_score']}.\n"
        "Write the Max & Nova dialogue now.",
        temperature=0.7,
    )

    rewrite_count = 0
    while True:
        fact_check = llm.generate_json(
            FACT_CHECK_SYSTEM_PROMPT,
            f"Fact-check this dialogue:\n\n{dialogue_transcript(script['dialogue'])}",
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
        script = llm.generate_json(
            REWRITE_SYSTEM_PROMPT,
            f"Original dialogue: {dialogue_transcript(script['dialogue'])}\n"
            f"Issues to fix: {', '.join(fact_check.get('issues', []))}",
            temperature=0.5,
        )
        rewrite_count += 1


def download_file(url: str, dest_path: str):
    resp = requests.get(url, timeout=60, stream=True)
    resp.raise_for_status()
    with open(dest_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=1 << 16):
            f.write(chunk)


def build_dialogue_video(scenes: list[dict], render_dir: str) -> str:
    """Synthesizes each line's voice, renders each turn as a talking-heads
    scene sized to that line's actual spoken duration, concatenates them, and
    mixes in ducked background music under the voices. Returns the final
    (pre-QC) video path."""
    font_path = os.environ.get("RENDER_FONT_PATH", video.FONT_PATH_DEFAULT)
    processed_paths = []
    for scene in scenes:
        idx = scene["index"]
        speaker = scene["speaker"]
        voice = VOICE_BY_SPEAKER[speaker]

        text_path = os.path.join(render_dir, f"scene_{idx}_line.txt")
        audio_path = os.path.join(render_dir, f"scene_{idx}_voice.mp3")
        caption_path = os.path.join(render_dir, f"scene_{idx}_caption.txt")
        processed_path = os.path.join(render_dir, f"scene_{idx}_processed.mp4")

        tts.synthesize(scene["text"], voice, text_path, audio_path)
        with open(caption_path, "w") as f:
            f.write(video.wrap_caption(scene["text"]))

        # a little tail padding so the mouth-flap and caption don't cut off
        # the instant the voice line ends
        duration = video.probe_duration(audio_path) + 0.4

        video.render_talking_scene(
            speaker, MAX_PORTRAIT, NOVA_PORTRAIT,
            caption_path, audio_path, duration, processed_path, font_path,
        )
        processed_paths.append(processed_path)

    list_path = os.path.join(render_dir, "concat_list.txt")
    with open(list_path, "w") as f:
        for p in processed_paths:
            f.write(f"file '{os.path.basename(p)}'\n")
    voiced_path = os.path.join(render_dir, "voiced.mp4")
    video.concat_scenes(list_path, voiced_path)

    music_path = os.path.join(render_dir, "music.mp3")
    download_file(os.environ["BG_MUSIC_URL"], music_path)
    final_path = os.path.join(render_dir, "final.mp4")
    video.mix_music(voiced_path, music_path, final_path)
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

    scenes = video.build_dialogue_scenes(script["dialogue"])
    log.info("Split into %d dialogue turns", len(scenes))

    run_id = video.safe_run_id(f"{topic['run_id']}-{topic['id']}")
    render_dir = os.path.join(tempfile.gettempdir(), "shorts-render", run_id)
    os.makedirs(render_dir, exist_ok=True)
    try:
        final_path = build_dialogue_video(scenes, render_dir)
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

        transcript = dialogue_transcript(script["dialogue"])
        seo = llm.generate_json(
            SEO_SYSTEM_PROMPT,
            f"Script title: {script['title']}\nDialogue: {transcript}",
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
        log.info("Uploaded to YouTube: video_id=%s publish_at=%s", video_id, publish_at)

        # Best-effort: setting a custom thumbnail requires the channel to have
        # completed phone verification (a YouTube-side restriction, unrelated to
        # OAuth scopes). The video itself is already live/scheduled at this point,
        # so a thumbnail failure must never lose the DB record or the notification
        # for a video that genuinely exists on the channel.
        try:
            set_thumbnail(video_id, thumb_path)
            thumbnail_status = "set"
        except Exception as e:  # noqa: BLE001
            log.warning("set_thumbnail failed for video_id=%s: %s", video_id, e)
            thumbnail_status = "failed"

        db.insert_rows(conn, "published_videos", [{
            "run_id": topic["run_id"], "topic_id": topic["id"], "youtube_video_id": video_id,
            "title": script["title"], "script": transcript,
            "fact_check_confidence": script["fact_check"]["confidence"], "rewrite_count": script["rewrite_count"],
            "thumbnail_status": thumbnail_status, "video_url": f"https://youtube.com/shorts/{video_id}",
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
