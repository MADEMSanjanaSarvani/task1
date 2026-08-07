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
