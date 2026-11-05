"""Candidate generation rules, including situations A to E from the project brief."""

from conftest import dialogue_rows, make_episode

from promo_finder.boundaries import (
    build_clip, cues_in_range, dialogue_in_progress, first_story_cue, intersection_over_union,
    is_continuation, is_meaningful, known_names_for,
)


def long_episode(count=30, seconds=3.0):
    return make_episode(dialogue_rows(0.0, count, seconds))


def pair(episode, first, last):
    return build_clip(episode, episode.cues[first], episode.cues[last])


def test_situation_a_valid_35_second_clip():
    episode = long_episode()
    result = pair(episode, 0, 11)  # 12 lines of 3 seconds each
    assert result.ok
    assert 20 <= result.clip.duration <= 60


def test_situation_b_too_long_is_rejected_not_trimmed():
    episode = long_episode(count=40)
    result = pair(episode, 0, 25)
    assert not result.ok and result.reason == "too_long"


def test_situation_c_too_short_is_rejected_not_stretched():
    episode = long_episode()
    result = pair(episode, 0, 3)
    assert not result.ok and result.reason == "too_short"


def test_situation_d_hook_must_start_within_three_seconds():
    episode = make_episode(
        [("CAMERA", 0.0, 1.0, "Wide shot of a garden."), ("ANNA (Cold)", 0.5, 1.0, "Hi.")]
        + dialogue_rows(1.0, 20)
    )
    result = build_clip(episode, episode.cues[2], episode.cues[15])
    assert result.ok
    assert result.clip.hook_offset <= 3.0


def test_situation_e_end_inside_a_line_moves_to_the_end_of_that_line():
    rows = dialogue_rows(0.0, 10)
    rows.append(("BEN (Cold)", 29.0, 33.0, "This line is still being spoken when the ending stops."))
    episode = make_episode(rows)
    result = build_clip(episode, episode.cues[0], episode.cues[9])
    assert result.ok
    assert result.clip.end == 33.0
    assert any("so that line is not cut" in note for note in result.clip.adjustments)


def test_situation_e_rejected_when_moving_would_pass_the_limit():
    rows = dialogue_rows(0.0, 20)
    rows.append(("BEN (Cold)", 58.0, 66.0, "A long overlapping line that would run past the limit."))
    episode = make_episode(rows)
    result = build_clip(episode, episode.cues[0], episode.cues[19])
    assert not result.ok and result.reason == "cuts_through_dialogue"


def test_clip_starting_inside_a_line_moves_back_when_the_hook_stays_within_three_seconds():
    rows = [("BEN (Cold)", 2.0, 5.0, "An earlier line still being spoken here.")] + dialogue_rows(4.0, 12)
    episode = make_episode(rows)
    result = build_clip(episode, episode.cues[1], episode.cues[10])
    assert result.ok and result.clip.start == 2.0
    assert any("still being spoken" in note for note in result.clip.adjustments)


def test_clip_starting_inside_a_line_is_rejected_when_moving_back_breaks_the_three_seconds():
    rows = [("BEN (Cold)", 0.0, 5.0, "An earlier line still being spoken here.")] + dialogue_rows(4.0, 12)
    episode = make_episode(rows)
    result = build_clip(episode, episode.cues[1], episode.cues[10])
    assert not result.ok and result.reason == "starts_inside_dialogue"


def test_times_always_come_from_cues_and_are_never_invented():
    episode = make_episode([("CAMERA", 0.0, 40.0, "Long shot.")] + dialogue_rows(1.0, 12))
    result = build_clip(episode, episode.cues[1], episode.cues[10])
    assert result.ok
    clip = result.clip
    assert episode.cue(clip.start_cue_id).start == clip.start
    assert episode.cue(clip.end_cue_id).end == clip.end


def test_camera_cue_cannot_be_a_hook():
    episode = make_episode([("CAMERA", 0.0, 2.0, "Wide shot of a garden.")] + dialogue_rows(2.0, 12))
    result = build_clip(episode, episode.cues[0], episode.cues[10])
    assert not result.ok and result.reason == "hook_not_a_story_event"


def test_sound_cue_cannot_be_an_ending():
    episode = make_episode(dialogue_rows(0.0, 12) + [("SOUND FX", 36.0, 38.0, "Strings swell to a cliffhanger.")])
    result = build_clip(episode, episode.cues[0], episode.cues[12])
    assert not result.ok and result.reason == "ending_not_a_story_event"


def test_ending_before_hook_is_rejected():
    episode = long_episode()
    result = pair(episode, 10, 2)
    assert not result.ok and result.reason == "ending_before_hook"


def test_cue_without_valid_time_is_rejected():
    episode = long_episode()
    episode.cues[0].start = None
    result = pair(episode, 0, 10)
    assert not result.ok and result.reason == "hook_has_no_valid_time"


def test_hook_that_continues_a_sentence_is_rejected():
    rows = dialogue_rows(0.0, 2) + [("ANNA (Cold)", 6.0, 8.0, "...and that is why you lost.")] + dialogue_rows(8.0, 12)
    episode = make_episode(rows)
    assert is_continuation(episode.cues[2])
    result = build_clip(episode, episode.cues[2], episode.cues[12])
    assert not result.ok and result.reason == "hook_starts_mid_sentence"


def test_bare_reply_or_name_cannot_open_a_clip():
    rows = [("ANNA (Cold)", 0.0, 1.0, "Yes."), ("BEN (Cold)", 1.0, 2.0, "Anna...")] + dialogue_rows(2.0, 12)
    episode = make_episode(rows)
    names = known_names_for(episode)
    assert not is_meaningful(episode.cues[0], names)
    assert not is_meaningful(episode.cues[1], names)
    assert build_clip(episode, episode.cues[0], episode.cues[10]).reason == "hook_not_meaningful"


def test_one_word_shock_is_still_meaningful():
    episode = make_episode([("ANNA (Cold)", 0.0, 1.0, "Poison.")])
    assert is_meaningful(episode.cues[0], known_names_for(episode))


def test_ending_mid_sentence_gets_a_warning():
    rows = dialogue_rows(0.0, 11)
    rows[10] = ("ANNA (Furious)", 30.0, 32.0, "And then I will tell them...")
    rows.append(("ANNA (Furious)", 32.0, 34.0, "...everything you did."))
    episode = make_episode(rows)
    result = build_clip(episode, episode.cues[0], episode.cues[10])
    assert result.ok
    assert any("mid sentence" in warning for warning in result.clip.warnings)


def test_snapping_to_a_shot_never_pushes_over_sixty_seconds():
    rows = dialogue_rows(0.0, 20)  # Last line ends at 59.8 seconds.
    rows.append(("CAMERA", 50.0, 61.0, "Hold on her face."))
    episode = make_episode(rows)
    result = build_clip(episode, episode.cues[0], episode.cues[19])
    assert result.ok
    assert result.clip.duration <= 60.0


def test_crossing_scenes_gets_a_warning(sample_zip):
    from promo_finder.parser import load_pack
    episodes, _ = load_pack(sample_zip)
    second = episodes[1]
    hook = next(cue for cue in second.cues if cue.text.startswith("The bakery"))
    ending = next(cue for cue in second.cues if "Someone has been living" in cue.text)
    result = build_clip(second, hook, ending)
    assert result.ok
    assert any("Crosses" in warning for warning in result.clip.warnings)


def test_dialogue_in_progress_and_range_helpers():
    episode = make_episode([("ANNA (Cold)", 1.0, 5.0, "A line."), ("BEN (Cold)", 5.0, 9.0, "Another line.")])
    assert dialogue_in_progress(episode, 3.0).cue_id == episode.cues[0].cue_id
    assert dialogue_in_progress(episode, 5.0) is None
    assert [cue.cue_id for cue in cues_in_range(episode, 0.0, 5.0)] == [episode.cues[0].cue_id]
    assert first_story_cue(episode, 0.0, 9.0).cue_id == episode.cues[0].cue_id


def test_iou_matches_the_worked_example():
    # Two 35 second clips sharing 30 seconds cover 40 seconds in total: 30 / 40 = 0.75.
    assert intersection_over_union(0, 35, 5, 40) == 0.75
    assert intersection_over_union(0, 10, 20, 30) == 0.0
    assert intersection_over_union(0, 10, 0, 10) == 1.0


def test_clip_does_not_open_partway_through_a_physical_action():
    rows = [("ACTION", 1.0, 5.0, "He strikes her hard across the shoulder with the whip."), ("ACTION", 3.0, 5.0, "She gasps in pain and bends over.")] + dialogue_rows(5.0, 12)
    episode = make_episode(rows)
    result = build_clip(episode, episode.cues[1], episode.cues[10])
    assert result.ok and result.clip.start == 1.0
    assert result.clip.start_cue_id == episode.cues[0].cue_id
    assert any("already happening" in note for note in result.clip.adjustments)


def test_long_action_too_far_back_does_not_move_the_start():
    rows = [("ACTION", 0.0, 12.0, "A long slow walk across the wide empty hall.")] + dialogue_rows(8.0, 12)
    episode = make_episode(rows)
    result = build_clip(episode, episode.cues[1], episode.cues[10])
    assert result.ok and result.clip.start == 8.0


def test_start_steps_back_through_overlapping_actions_to_the_cause():
    rows = [
        ("ACTION", 1.0, 3.5, "He strikes her hard across the shoulder."),
        ("ACTION", 3.0, 5.5, "She gasps in pain and bends over."),
    ] + dialogue_rows(4.0, 12)
    episode = make_episode(rows)
    result = build_clip(episode, episode.cues[2], episode.cues[11])
    assert result.ok and result.clip.start == 1.0
    assert result.clip.hook_offset <= 3.0
