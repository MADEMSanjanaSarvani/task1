from common import tts


def test_synthesize_args_use_argv_list_not_shell_string():
    args = tts.build_synthesize_args("/r/1/line.txt", "en-US-GuyNeural", "/r/1/voice.mp3")
    assert args[0] == "edge-tts"
    assert "/r/1/line.txt" in args
    assert "/r/1/voice.mp3" in args
    assert "en-US-GuyNeural" in args
    assert all(";" not in a and "&&" not in a and "|" not in a for a in args)


def test_max_and_nova_use_distinct_voices():
    assert tts.MAX_VOICE != tts.NOVA_VOICE
