import pytest

from common import video


def test_build_scenes_splits_on_sentence_boundaries():
    scenes = video.build_scenes("AI tools are booming. Freelancers use them daily! Are you missing out?")
    assert len(scenes) == 3
    assert [s["index"] for s in scenes] == [0, 1, 2]
    assert scenes[0]["text"] == "AI tools are booming."
    for s in scenes:
        assert s["search_query"], "search_query should never be empty"
        assert "{{" not in s["search_query"] and "}}" not in s["search_query"]


def test_build_scenes_caps_at_max_scenes():
    long_script = ". ".join([f"Sentence number {i}" for i in range(20)]) + "."
    scenes = video.build_scenes(long_script, max_scenes=10)
    assert len(scenes) == 10


def test_build_scenes_strips_stopwords_from_search_query():
    scenes = video.build_scenes("This is the way to make money with AI tools fast.")
    # "This", "is", "the", "to", "with" are stopwords and should be dropped
    query_words = scenes[0]["search_query"].lower().split()
    assert "this" not in query_words
    assert "the" not in query_words


def test_process_scene_args_are_argv_list_not_shell_string():
    args = video.build_process_scene_args("/r/1/raw.mp4", "/r/1/cap.txt", "/r/1/out.mp4", 4.0)
    assert args[0] == "ffmpeg"
    assert "/r/1/raw.mp4" in args
    assert "/r/1/out.mp4" in args
    # every element is a separate argv entry - no shell metacharacters are ever
    # needed here since subprocess.run(args, shell=False) never parses a string
    assert all(";" not in a and "&&" not in a and "|" not in a for a in args)


def test_concat_args_reference_both_paths():
    args = video.build_concat_args("/r/1/concat_list.txt", "/r/1/novoice.mp4")
    assert "/r/1/concat_list.txt" in args
    assert "/r/1/novoice.mp4" in args
    assert "concat" in args


def test_mix_music_args_include_shortest_flag():
    args = video.build_mix_music_args("/r/1/novoice.mp4", "/r/1/music.mp3", "/r/1/final.mp4")
    assert "-shortest" in args
    assert "/r/1/music.mp3" in args


def test_probe_args_target_ffprobe():
    args = video.build_probe_args("/r/1/final.mp4")
    assert args[0] == "ffprobe"
    assert "/r/1/final.mp4" in args


def test_thumbnail_args_include_drawtext():
    args = video.build_thumbnail_args("/r/1/final.mp4", "/r/1/title.txt", "/r/1/thumb.jpg")
    assert any("drawtext" in a for a in args)
    assert "/r/1/thumb.jpg" in args


def test_wrap_caption_keeps_short_lines_unwrapped():
    assert video.wrap_caption("Short line.") == "Short line."


def test_wrap_caption_wraps_long_lines_without_cutting_words():
    text = "You could think the code and have it appear right on your screen instantly."
    wrapped = video.wrap_caption(text, max_chars=34)
    lines = wrapped.split("\n")
    assert len(lines) > 1
    assert all(len(line) <= 34 for line in lines)
    # no words lost or mangled by wrapping
    assert " ".join(lines).split() == text.split()


def test_wrap_caption_never_exceeds_max_chars_even_for_one_long_word():
    wrapped = video.wrap_caption("a " * 2 + "supercalifragilisticexpialidocious", max_chars=10)
    assert all(len(line) for line in wrapped.split("\n"))


def test_build_dialogue_scenes_normalizes_turns():
    dialogue = [
        {"speaker": "Max", "line": "AI tools are booming right now."},
        {"speaker": "Nova", "line": "Here's how you can cash in on it."},
    ]
    scenes = video.build_dialogue_scenes(dialogue)
    assert len(scenes) == 2
    assert scenes[0] == {"index": 0, "speaker": "Max", "text": "AI tools are booming right now."}
    assert scenes[1]["speaker"] == "Nova"


def test_build_dialogue_scenes_drops_invalid_turns():
    dialogue = [
        {"speaker": "Max", "line": "Valid line."},
        {"speaker": "Someone Else", "line": "Unknown speaker, should be dropped."},
        {"speaker": "Nova", "line": ""},
        {"speaker": "Nova", "line": "Also valid."},
    ]
    scenes = video.build_dialogue_scenes(dialogue)
    assert len(scenes) == 2
    assert [s["speaker"] for s in scenes] == ["Max", "Nova"]


def test_build_dialogue_scenes_caps_at_max_scenes():
    dialogue = [{"speaker": "Max" if i % 2 == 0 else "Nova", "line": f"Line {i}"} for i in range(20)]
    scenes = video.build_dialogue_scenes(dialogue, max_scenes=10)
    assert len(scenes) == 10


def test_talking_scene_args_are_argv_list_not_shell_string():
    args = video.build_talking_scene_args(
        "Max", "/a/max.png", "/a/nova.png", "/r/1/cap.txt", "/r/1/voice.mp3", 3.5, "/r/1/out.mp4",
    )
    assert args[0] == "ffmpeg"
    assert "/r/1/voice.mp3" in args
    assert "/r/1/out.mp4" in args
    # ";" is expected *inside* the -filter_complex value (ffmpeg's own filter-graph
    # chaining syntax) - it's still a single argv element, never shell-parsed, since
    # subprocess.run(args, shell=False) never invokes a shell. "&&"/"|" would only
    # matter if this were built as a shell string, which it never is here.
    assert all("&&" not in a and "|" not in a for a in args)


def test_talking_scene_args_map_audio_from_voice_input():
    args = video.build_talking_scene_args(
        "Nova", "/a/max.png", "/a/nova.png", "/r/1/cap.txt", "/r/1/voice.mp3", 3.5, "/r/1/out.mp4",
    )
    assert "3:a" in args  # the audio input (index 3: color + 2 char images + audio)


def test_talking_scene_args_scale_preserves_aspect_ratio():
    args = video.build_talking_scene_args(
        "Max", "/a/max.png", "/a/nova.png", "/r/1/cap.txt", "/r/1/voice.mp3", 3.5, "/r/1/out.mp4",
    )
    filter_arg = args[args.index("-filter_complex") + 1]
    assert "force_original_aspect_ratio=decrease" in filter_arg


def test_talking_scene_args_rejects_unknown_speaker():
    with pytest.raises(ValueError):
        video.build_talking_scene_args(
            "Bob", "/a/max.png", "/a/nova.png", "/r/1/cap.txt", "/r/1/voice.mp3", 3.5, "/r/1/out.mp4",
        )


def test_mix_music_args_mix_voice_and_ducked_music_not_replace():
    args = video.build_mix_music_args("/r/1/voiced.mp4", "/r/1/music.mp3", "/r/1/final.mp4")
    filter_arg = args[args.index("-filter_complex") + 1]
    assert "amix" in filter_arg
    assert "[0:a]" in filter_arg  # the original voice track is still referenced, not discarded


def test_safe_run_id_passes_through_clean_input():
    assert video.safe_run_id("20260727-123") == "20260727-123"


def test_safe_run_id_strips_shell_unsafe_characters():
    sanitized = video.safe_run_id("run-1; rm -rf /")
    assert not any(c in sanitized for c in [";", "/", " "])


def test_safe_run_id_rejects_empty_result():
    with pytest.raises(ValueError):
        video.safe_run_id("   ")

    with pytest.raises(ValueError):
        video.safe_run_id(";;;")
