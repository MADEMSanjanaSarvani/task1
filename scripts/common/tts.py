"""Free text-to-speech via edge-tts (an unofficial wrapper around Microsoft
Edge's read-aloud service) - no API key, no cost, argument-list subprocess
calls only (no shell string). It's not an officially supported API, so if
it ever breaks, this is the only place that needs to change - every caller
just depends on synthesize().
"""
import subprocess

MAX_VOICE = "en-US-GuyNeural"
NOVA_VOICE = "en-US-AriaNeural"


def build_synthesize_args(text_path: str, voice: str, out_path: str) -> list[str]:
    return ["edge-tts", "--voice", voice, "--file", text_path, "--write-media", out_path]


def synthesize(text: str, voice: str, text_path: str, out_path: str):
    with open(text_path, "w") as f:
        f.write(text)
    result = subprocess.run(build_synthesize_args(text_path, voice, out_path), capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"edge-tts failed (voice={voice}): {result.stderr[-2000:]}")
