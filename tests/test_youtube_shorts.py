import importlib.util
import os


def _load_youtube_shorts_module():
    """05_youtube_shorts.py starts with a digit, so it can't be imported with
    a normal `import` statement - load it by file path instead."""
    path = os.path.join(os.path.dirname(__file__), "..", "scripts", "05_youtube_shorts.py")
    spec = importlib.util.spec_from_file_location("youtube_shorts_module", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_normalize_dialogue_passes_through_well_formed_turns():
    mod = _load_youtube_shorts_module()
    dialogue = [{"speaker": "Max", "line": "AI tools are booming."}]
    assert mod.normalize_dialogue(dialogue) == dialogue


def test_normalize_dialogue_coerces_plain_speaker_colon_line_strings():
    """Llama models via Groq's json_object mode sometimes return each turn as
    a plain "Speaker: line" string instead of the requested {speaker, line}
    object - this used to crash every downstream consumer with a bare
    TypeError ("string indices must be integers")."""
    mod = _load_youtube_shorts_module()
    dialogue = ["Max: AI tools are booming.", "Nova: Here's how to cash in."]
    normalized = mod.normalize_dialogue(dialogue)
    assert normalized == [
        {"speaker": "Max", "line": "AI tools are booming."},
        {"speaker": "Nova", "line": "Here's how to cash in."},
    ]


def test_normalize_dialogue_drops_unparseable_turns_without_crashing():
    mod = _load_youtube_shorts_module()
    dialogue = [{"speaker": "Max", "line": "Valid."}, "no colon here", 42]
    normalized = mod.normalize_dialogue(dialogue)
    assert normalized == [{"speaker": "Max", "line": "Valid."}]


def test_dialogue_transcript_formats_speaker_and_line():
    mod = _load_youtube_shorts_module()
    dialogue = [{"speaker": "Max", "line": "Hi."}, {"speaker": "Nova", "line": "Hey."}]
    assert mod.dialogue_transcript(dialogue) == "Max: Hi.\nNova: Hey."
