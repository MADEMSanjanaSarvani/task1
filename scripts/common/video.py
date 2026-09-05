"""FFmpeg/ffprobe wrappers for the Shorts pipeline.

Every ffmpeg/ffprobe invocation is built as an argument LIST (never a shell
string), so there's no shell-injection surface at all - unlike the n8n version,
which had to carefully sanitize path components before interpolating them into
an Execute Command shell string, subprocess.run(args_list, shell=False) never
invokes a shell to parse anything, so this is safe by construction rather than
by sanitization.
"""
import logging
import subprocess

log = logging.getLogger(__name__)

FONT_PATH_DEFAULT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"  # apt package fonts-dejavu-core

# Two-character "talking heads" layout - Max always occupies the left half of
# the 1080x1920 canvas, Nova always the right half, side by side in a fixed
# character zone with a full-width caption strip below, so the channel has a
# consistent, recognizable look every Short. Nova is horizontally mirrored so
# she visually faces Max (toward the center) instead of both facing the
# camera dead-on, which read as two people talking *at the viewer*, not to
# each other.
CANVAS_W, CANVAS_H = 1080, 1920
HALF_W = CANVAS_W // 2
CHAR_ZONE_H = 1100
CHAR_DISPLAY_W, CHAR_DISPLAY_H = 480, 900
MAX_PANEL_X, NOVA_PANEL_X = 0, HALF_W
MAX_BG, NOVA_BG = "0x0B1220", "0x2E0C2E"
MAX_ACCENT, NOVA_ACCENT = "0xF59E0B", "0xEC4899"
# fraction of each 0.4s cycle the brighter glow ring is shown on top of the
# speaking panel's static border - a pulsing "who's talking" indicator that
# only needs one portrait per character, not a matched mouth-open/closed pair.
PULSE_ENABLE = "lt(mod(t,0.4),0.18)"

CAPTION_FONTSIZE = 40
CAPTION_MAX_CHARS_PER_LINE = 34  # ~fits CAPTION_FONTSIZE within the 1080px canvas width


def wrap_caption(text: str, max_chars: int = CAPTION_MAX_CHARS_PER_LINE) -> str:
    """Word-wraps a caption line into multiple lines so drawtext never renders
    text wider than the video frame - a single un-wrapped sentence at this
    fontsize can easily exceed 1080px and run off both edges."""
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) > max_chars and current:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return "\n".join(lines)


def _run(args: list[str]):
    log.info("Running: %s", " ".join(args))
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Command failed ({result.returncode}): {' '.join(args)}\nstderr: {result.stderr[-2000:]}")
    return result


def build_process_scene_args(raw_path: str, caption_path: str, out_path: str,
                              duration: float, font_path: str = FONT_PATH_DEFAULT) -> list[str]:
    vf = (
        "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,fps=30,"
        f"drawtext=fontfile={font_path}:textfile={caption_path}:fontcolor=white:fontsize=54:"
        "x=(w-text_w)/2:y=h-380:box=1:boxcolor=black@0.55:boxborderw=24"
    )
    return [
        "ffmpeg", "-y", "-i", raw_path, "-t", str(duration), "-vf", vf,
        "-an", "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", out_path,
    ]


def process_scene(raw_path: str, caption_path: str, out_path: str, duration: float,
                   font_path: str = FONT_PATH_DEFAULT):
    _run(build_process_scene_args(raw_path, caption_path, out_path, duration, font_path))


def build_concat_args(list_path: str, out_path: str) -> list[str]:
    return ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_path, "-c", "copy", out_path]


def concat_scenes(list_path: str, out_path: str):
    _run(build_concat_args(list_path, out_path))


def build_mix_music_args(video_path: str, music_path: str, out_path: str) -> list[str]:
    """Ducks the background music well under the characters' TTS voice track
    (already embedded in video_path from the per-scene dialogue audio) rather
    than replacing it - amix blends both into one output track."""
    filter_complex = (
        "[0:a]volume=1.0[voice];[1:a]volume=0.12[bg];"
        "[voice][bg]amix=inputs=2:duration=first:dropout_transition=0[aout]"
    )
    return [
        "ffmpeg", "-y", "-i", video_path, "-stream_loop", "-1", "-i", music_path,
        "-filter_complex", filter_complex, "-map", "0:v", "-map", "[aout]",
        "-shortest", "-c:v", "copy", "-c:a", "aac", "-movflags", "+faststart", out_path,
    ]


def mix_music(video_path: str, music_path: str, out_path: str):
    _run(build_mix_music_args(video_path, music_path, out_path))


def build_probe_args(video_path: str) -> list[str]:
    return ["ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", video_path]


def probe_duration(video_path: str) -> float:
    result = _run(build_probe_args(video_path))
    return float(result.stdout.strip())


def build_thumbnail_args(video_path: str, title_path: str, out_path: str,
                          font_path: str = FONT_PATH_DEFAULT) -> list[str]:
    vf = (
        f"drawtext=fontfile={font_path}:textfile={title_path}:fontcolor=white:fontsize=64:"
        "x=(w-text_w)/2:y=120:box=1:boxcolor=black@0.6:boxborderw=30"
    )
    return ["ffmpeg", "-y", "-i", video_path, "-ss", "00:00:01", "-vframes", "1", "-vf", vf, out_path]


def extract_thumbnail(video_path: str, title_path: str, out_path: str, font_path: str = FONT_PATH_DEFAULT):
    _run(build_thumbnail_args(video_path, title_path, out_path, font_path))


def build_scenes(script_text: str, max_scenes: int = 10, scene_duration: float = 4.0) -> list[dict]:
    """Split a script into caption-card scenes with a short stock-footage search
    query derived from each sentence's keywords (mirrors the n8n Code node logic)."""
    import re

    stopwords = {
        "the", "a", "an", "is", "are", "to", "of", "in", "on", "for", "and", "with",
        "your", "you", "this", "that", "it", "as", "at", "by", "be", "can", "will",
        "how", "what", "why",
    }
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", script_text) if s.strip()][:max_scenes]
    scenes = []
    for i, s in enumerate(sentences):
        words = [w for w in re.sub(r"[^a-zA-Z0-9 ]", "", s).split() if w.lower() not in stopwords]
        search_query = " ".join(words[:4]) or "business technology"
        scenes.append({"index": i, "text": s, "search_query": search_query, "duration": scene_duration})
    return scenes


def build_dialogue_scenes(dialogue: list[dict], max_scenes: int = 14) -> list[dict]:
    """Normalizes the LLM's raw dialogue turns (list of {speaker, line}) into
    indexed scenes for the two-character talking-heads renderer. Each scene's
    duration is filled in later by the caller, after its TTS line is synthesized
    and probed - a turn's length is however long the line actually takes to say,
    not a fixed guess."""
    scenes = []
    for i, turn in enumerate(dialogue[:max_scenes]):
        speaker = (turn.get("speaker") or "").strip()
        line = (turn.get("line") or "").strip()
        if speaker not in ("Max", "Nova") or not line:
            continue
        scenes.append({"index": i, "speaker": speaker, "text": line})
    return scenes


def build_talking_scene_args(speaker: str, max_path: str, nova_path: str, caption_path: str,
                              audio_path: str, duration: float, out_path: str,
                              font_path: str = FONT_PATH_DEFAULT) -> list[str]:
    """Builds one dialogue-turn scene: Max and Nova side by side (facing each
    other, not the camera), a pulsing glow ring around whichever one is
    speaking, and the line's caption burned into a full-width strip below -
    with the line's own TTS audio as this scene's soundtrack."""
    if speaker not in ("Max", "Nova"):
        raise ValueError(f"unknown speaker: {speaker!r}")

    speaking_max = speaker == "Max"
    highlight_x = MAX_PANEL_X if speaking_max else NOVA_PANEL_X
    highlight_color = MAX_ACCENT if speaking_max else NOVA_ACCENT

    bg = (
        f"[0:v]drawbox=x=0:y=0:w={HALF_W}:h={CHAR_ZONE_H}:color={MAX_BG}:t=fill,"
        f"drawbox=x={HALF_W}:y=0:w={HALF_W}:h={CHAR_ZONE_H}:color={NOVA_BG}:t=fill,"
        f"drawbox=x={HALF_W - 6}:y=0:w=12:h={CHAR_ZONE_H}:color=0xF59E0B:t=fill,"
        f"drawbox=x={highlight_x + 6}:y=6:w={HALF_W - 12}:h={CHAR_ZONE_H - 12}:"
        f"color={highlight_color}:t=14,"
        f"drawbox=x={highlight_x + 2}:y=2:w={HALF_W - 4}:h={CHAR_ZONE_H - 4}:"
        f"color=white@0.6:t=6:enable='{PULSE_ENABLE}'[bg]"
    )

    scale_chars = (
        # character portraits are expected on a plain white background (not
        # transparent) - colorkey strips it to alpha here. It overwrites any
        # existing alpha channel wholesale, so don't feed this a PNG that's
        # already transparent; every portrait in assets/characters/ is flat
        # RGB on white, by design, to keep this assumption simple and true.
        f"[1:v]scale={CHAR_DISPLAY_W}:{CHAR_DISPLAY_H}:force_original_aspect_ratio=decrease,"
        f"colorkey=0xFFFFFF:0.12:0.08[maxc];"
        # hflip mirrors Nova so she visually faces Max (toward the center) instead
        # of both characters facing the camera dead-on, which read as talking at
        # the viewer rather than to each other.
        f"[2:v]hflip,scale={CHAR_DISPLAY_W}:{CHAR_DISPLAY_H}:force_original_aspect_ratio=decrease,"
        f"colorkey=0xFFFFFF:0.12:0.08[novac]"
    )
    # centered by expression (not a fixed x/y) since force_original_aspect_ratio
    # doesn't guarantee the scaled image fills CHAR_DISPLAY_W x CHAR_DISPLAY_H
    # exactly - a portrait narrower or shorter than the box would otherwise
    # land off-center within its half.
    max_center_x = f"({MAX_PANEL_X}+({HALF_W}-overlay_w)/2)"
    nova_center_x = f"({NOVA_PANEL_X}+({HALF_W}-overlay_w)/2)"
    center_y = "((" + str(CHAR_ZONE_H) + "-overlay_h)/2)"
    overlays = (
        f"[bg][maxc]overlay=x='{max_center_x}':y='{center_y}'[m1];"
        f"[m1][novac]overlay=x='{nova_center_x}':y='{center_y}'[n1]"
    )

    caption = (
        f"[n1]drawtext=fontfile={font_path}:textfile={caption_path}:fontcolor=white:"
        f"fontsize={CAPTION_FONTSIZE}:x=(w-text_w)/2:y={CHAR_ZONE_H + 60}:"
        "box=1:boxcolor=black@0.55:boxborderw=20[vout]"
    )

    filter_complex = ";".join([bg, scale_chars, overlays, caption])

    return [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"color=c=black:s={CANVAS_W}x{CANVAS_H}",
        "-loop", "1", "-i", max_path,
        "-loop", "1", "-i", nova_path,
        "-i", audio_path,
        "-filter_complex", filter_complex,
        "-map", "[vout]", "-map", "3:a",
        "-t", str(duration),
        "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", out_path,
    ]


def render_talking_scene(speaker: str, max_path: str, nova_path: str, caption_path: str,
                          audio_path: str, duration: float, out_path: str,
                          font_path: str = FONT_PATH_DEFAULT):
    _run(build_talking_scene_args(speaker, max_path, nova_path, caption_path,
                                   audio_path, duration, out_path, font_path))


def safe_run_id(run_id: str) -> str:
    """Sanitizes a run_id for use as a directory name - defense in depth even
    though argument-list subprocess calls don't have a shell-injection surface,
    since a run_id also gets used to build a filesystem path."""
    import re

    cleaned = re.sub(r"[^a-zA-Z0-9._-]", "", str(run_id))
    if not cleaned:
        raise ValueError(f"unsafe/empty run_id: {run_id!r}")
    return cleaned
