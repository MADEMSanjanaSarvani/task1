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
    return [
        "ffmpeg", "-y", "-i", video_path, "-stream_loop", "-1", "-i", music_path,
        "-filter_complex", "[1:a]volume=0.25[bg]", "-map", "0:v", "-map", "[bg]",
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


def safe_run_id(run_id: str) -> str:
    """Sanitizes a run_id for use as a directory name - defense in depth even
    though argument-list subprocess calls don't have a shell-injection surface,
    since a run_id also gets used to build a filesystem path."""
    import re

    cleaned = re.sub(r"[^a-zA-Z0-9._-]", "", str(run_id))
    if not cleaned:
        raise ValueError(f"unsafe/empty run_id: {run_id!r}")
    return cleaned
