"""File reading, timestamp conversion, cue and scene extraction, and data problems."""

from conftest import make_episode

from promo_finder.parser import (
    ACTION, CAMERA, DIALOGUE, SOUND, format_timestamp, load_pack, parse_episode_text, parse_timestamp, split_label,
)


def issue_types(episode):
    return {issue.issue_type for issue in episode.issues}


def test_timestamp_conversion_both_ways():
    assert parse_timestamp("01:04.80") == 64.8
    assert parse_timestamp("00:00.00") == 0.0
    assert format_timestamp(64.8) == "01:04.80"
    assert format_timestamp(0) == "00:00.00"
    assert parse_timestamp(format_timestamp(118.37)) == 118.37


def test_invalid_timestamps_return_none():
    for bad in ("", "1:2:3", "abc", "00:75.00", "12.5", "-1:00.00"):
        assert parse_timestamp(bad) is None


def test_labels_are_split_without_merging_people():
    assert split_label("LADY ANNA (Confused, Breathless)") == (DIALOGUE, "LADY ANNA", "Confused, Breathless", "on_screen")
    assert split_label("ANNA (V.O.) (Reflective)") == (DIALOGUE, "ANNA", "Reflective", "voice_over")
    assert split_label("OLD SAILOR (O.S.)") == (DIALOGUE, "OLD SAILOR", None, "off_screen")
    assert split_label("CAMERA")[0] == CAMERA
    assert split_label("ACTION")[0] == ACTION
    assert split_label("SOUND FX")[0] == SOUND
    # LADY ANNA and ANNA stay as different labels at this level.
    assert split_label("LADY ANNA")[1] != split_label("ANNA")[1]


def test_sample_pack_cues_have_unique_ids(sample_zip):
    episodes, issues = load_pack(sample_zip)
    assert [episode.number for episode in episodes] == [1, 2, 3]
    assert issues == []
    ids = [cue.cue_id for episode in episodes for cue in episode.cues]
    assert len(ids) == len(set(ids))
    assert ids[0] == "E01_C0001"
    assert all(cue.has_valid_time for episode in episodes for cue in episode.cues)


def test_uppercase_scene_labels_parse_the_same(sample_zip):
    episodes, _ = load_pack(sample_zip)
    second = episodes[1]
    assert second.label_style == "uppercase"
    assert second.scenes[0].heading and second.scenes[0].start == 0.0 and second.scenes[0].end == 30.0
    assert episodes[0].label_style == "titlecase"


def test_dialogue_quotes_removed_and_words_unchanged():
    episode = make_episode([("ANNA (Cold)", 1.0, 3.0, "You lied.")])
    assert episode.cues[0].text == "You lied."
    assert episode.cues[0].delivery == "Cold"


def _text_with_time_line(time_line):
    return (
        "EPISODE NUMBER: Episode 1\nEPISODE LOGLINE: x\nCONTINUITY NOTES: y\n\n--- SCRIPT START ---\n\n"
        "SCENE 01\nScene heading: INT. ROOM\nScene start: 00:00.00\nScene end: 01:00.00\n\nActions and dialogue:\n\n"
        f"**ANNA (Cold):**\n{time_line}\n\"Hello there.\"\n\n--- SCRIPT END ---\n"
    )


def test_missing_start_is_recorded_not_dropped():
    episode = parse_episode_text(_text_with_time_line("Start: () | End: (00:05.00)"), "e1.txt")
    assert len(episode.cues) == 1 and not episode.cues[0].has_valid_time
    assert "missing_start" in issue_types(episode)


def test_missing_end_is_recorded():
    episode = parse_episode_text(_text_with_time_line("Start: (00:05.00) | End: ()"), "e1.txt")
    assert "missing_end" in issue_types(episode)


def test_invalid_format_is_recorded():
    episode = parse_episode_text(_text_with_time_line("Start: (5 seconds) | End: (00:09.00)"), "e1.txt")
    assert "invalid_start" in issue_types(episode)
    assert episode.cues[0].start is None


def test_end_before_start_is_recorded():
    episode = parse_episode_text(_text_with_time_line("Start: (00:09.00) | End: (00:05.00)"), "e1.txt")
    assert "end_not_after_start" in issue_types(episode)
    assert not episode.cues[0].has_valid_time


def test_missing_time_line_is_recorded():
    text = _text_with_time_line("Start: (00:01.00) | End: (00:02.00)").replace("Start: (00:01.00) | End: (00:02.00)\n", "")
    episode = parse_episode_text(text, "e1.txt")
    assert "missing_timestamp" in issue_types(episode)


def test_overlap_within_a_track_is_recorded_but_camera_over_dialogue_is_not():
    episode = make_episode([
        ("CAMERA", 0.0, 10.0, "Wide shot."),
        ("ANNA (Cold)", 1.0, 5.0, "First line."),
        ("BEN (Cold)", 3.0, 6.0, "Overlapping line."),
    ])
    types = [issue.issue_type for issue in episode.issues]
    assert types.count("overlap_dialogue") == 1
    assert "overlap_camera" not in types


def test_cue_beyond_scene_end_is_recorded():
    episode = make_episode([("ANNA (Cold)", 1.0, 70.0, "Long line.")], end=60.0)
    assert "cue_after_scene_end" in issue_types(episode)


def test_repeated_cue_is_recorded_and_kept():
    episode = make_episode([("ANNA (Cold)", 1.0, 3.0, "Same line."), ("ANNA (Cold)", 1.0, 3.0, "Same line.")])
    assert "repeated_cue" in issue_types(episode)
    assert len(episode.cues) == 2


def test_incomplete_scene_is_recorded():
    text = (
        "EPISODE NUMBER: Episode 1\nEPISODE LOGLINE: x\nCONTINUITY NOTES: y\n\n--- SCRIPT START ---\n\n"
        "SCENE 01\nScene heading: INT. ROOM\nScene start: 00:00.00\n\nActions and dialogue:\n\n"
        "**ANNA (Cold):**\nStart: (00:01.00) | End: (00:02.00)\n\"Hello.\"\n\n--- SCRIPT END ---\n"
    )
    assert "incomplete_scene" in issue_types(parse_episode_text(text, "e1.txt"))


def test_unrecognised_line_is_recorded():
    text = _text_with_time_line("Start: (00:01.00) | End: (00:02.00)").replace("--- SCRIPT END ---", "A stray note\n\n--- SCRIPT END ---")
    assert "unrecognised_line" in issue_types(parse_episode_text(text, "e1.txt"))
