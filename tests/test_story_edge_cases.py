"""Story situations that simple rules get wrong, and how Basic mode's signals treat them.

These pin down behaviour, including its known limits. Basic mode only sees signals,
so it is fine for some of these to be caught only by the AI assisted blind tests.
"""

from conftest import dialogue_rows, make_episode

from promo_finder.basic_mode import MIN_ENDING_PART, candidates_for_episode, score_clip
from promo_finder.boundaries import build_clip
from promo_finder.masking import blind_clip, collect_labels, pack_name_words, speaker_root
from promo_finder.signals import delivery_level, ending_signal, hook_signal, is_physical_event, key_moment_signal, understanding_signal


def test_strong_dialogue_without_action_can_hook():
    episode = make_episode([("ANNA (Screaming, Furious)", 0.0, 2.0, "You poisoned my sister!")] + dialogue_rows(2.0, 12))
    assert hook_signal(episode, episode.cues[0]).value >= 0.5


def test_strong_action_without_dialogue_can_hook():
    episode = make_episode([("ACTION", 0.0, 2.0, "He slams her against the wall and grabs her throat.")] + dialogue_rows(6.0, 12))
    assert is_physical_event(episode.cues[0])
    assert hook_signal(episode, episode.cues[0]).value >= 0.35


def test_normal_question_scores_lower_than_tense_question():
    calm = make_episode([("ANNA (Gentle)", 0.0, 2.0, "What time should we open the shop tomorrow?"),
                         ("BEN (Calm)", 2.0, 4.0, "Nine, I suppose.")])
    tense = make_episode([("ANNA (Desperate, Terrified)", 0.0, 2.0, "Who put the poison in her cup?"),
                          ("BEN (Calm)", 2.0, 4.0, "I cannot say.")])
    assert ending_signal(calm, calm.cues[0]).value < ending_signal(tense, tense.cues[0]).value
    assert ending_signal(calm, calm.cues[0]).value * 100 < MIN_ENDING_PART


def test_dramatic_word_in_ordinary_talk_does_not_make_a_strong_hook():
    # Basic mode only looks at signals, so the word still adds a little. The soft
    # delivery keeps it well under a real accusation. The blind hook test handles the rest.
    ordinary = make_episode([("ANNA (Gentle, Warm)", 0.0, 2.0, "The bakery is dead on Mondays, you know.")])
    real = make_episode([("ANNA (Screaming, Furious)", 0.0, 2.0, "You killed him and you lied to me!")])
    assert hook_signal(ordinary, ordinary.cues[0]).value < 0.5
    assert hook_signal(ordinary, ordinary.cues[0]).value < hook_signal(real, real.cues[0]).value


def test_ending_that_resolves_the_conflict_is_marked_down():
    resolved = make_episode([("ANNA (Warm, Relieved)", 0.0, 2.0, "It is over. Thank you, you saved me.")] + [("ACTION", 2.0, 4.0, "Nothing else follows here at all.")])
    assert ending_signal(resolved, resolved.cues[0]).value < 0.2


def test_sound_description_with_the_word_cliffhanger_changes_nothing():
    rows = dialogue_rows(0.0, 12)
    without = make_episode(rows)
    with_word = make_episode(rows + [("SOUND FX", 36.0, 40.0, "Music swells to a huge cliffhanger sting.")])
    clip_a = build_clip(without, without.cues[0], without.cues[11]).clip
    clip_b = build_clip(with_word, with_word.cues[0], with_word.cues[11]).clip
    assert score_clip(without, clip_a, 10).parts["ending"] == score_clip(with_word, clip_b, 10).parts["ending"]


def test_camera_text_with_the_word_cliffhanger_changes_nothing():
    rows = dialogue_rows(0.0, 12)
    plain = make_episode(rows + [("CAMERA", 36.0, 40.0, "Hold on her face.")])
    worded = make_episode(rows + [("CAMERA", 36.0, 40.0, "Hold on her face for the cliffhanger.")])
    clip_a = build_clip(plain, plain.cues[0], plain.cues[11]).clip
    clip_b = build_clip(worded, worded.cues[0], worded.cues[11]).clip
    assert score_clip(plain, clip_a, 10).parts["ending"] == score_clip(worded, clip_b, 10).parts["ending"]


def test_clip_needing_earlier_context_scores_lower_on_understanding():
    needs_context = make_episode([(("ANNA (Cold)" if i % 2 == 0 else "BEN (Cold)"), i * 3.0, i * 3.0 + 2.8, "You know what happened yesterday, remember?") for i in range(12)])
    clear = make_episode([(("ANNA (Cold)" if i % 2 == 0 else "BEN (Cold)"), i * 3.0, i * 3.0 + 2.8, "You left me at the altar to marry my own sister and betrayed our family!") for i in range(12)])
    clip_a = build_clip(needs_context, needs_context.cues[0], needs_context.cues[11]).clip
    clip_b = build_clip(clear, clear.cues[0], clear.cues[11]).clip
    assert score_clip(needs_context, clip_a, 10).parts["understanding"] < score_clip(clear, clip_b, 10).parts["understanding"]


def test_late_story_clips_carry_a_position_penalty():
    episode = make_episode(dialogue_rows(0.0, 12), number=50)
    clip = build_clip(episode, episode.cues[0], episode.cues[11]).clip
    assert score_clip(episode, clip, 50).penalties["late_story_position"] == 10.0


def test_multiple_descriptions_of_one_event_do_not_count_twice():
    # A camera cue and an action cue describe one strike. Only the action cue counts.
    both = make_episode([("ACTION", 0.0, 2.0, "He strikes her."), ("CAMERA", 0.0, 2.0, "He strikes her in slow motion.")])
    one = make_episode([("ACTION", 0.0, 2.0, "He strikes her.")])
    assert hook_signal(both, both.cues[0]).value == hook_signal(one, one.cues[0]).value


def test_label_identity_is_not_assumed():
    labels = {"LADY ANNA", "ANNA", "LORD GREY", "LADY GREY", "THE OLD FRIEND"}
    assert speaker_root("LADY ANNA", labels) == "ANNA"
    assert speaker_root("LORD GREY", labels) != speaker_root("LADY GREY", labels)
    assert speaker_root("THE OLD FRIEND", labels) != "ANNA"


def test_delivery_note_reading():
    episode = make_episode([("ANNA (Screaming)", 0.0, 1.0, "One"), ("ANNA (Gentle)", 1.0, 2.0, "Two"), ("ANNA", 2.0, 3.0, "Three")])
    assert delivery_level(episode.cues[0]) == 1.0
    assert delivery_level(episode.cues[1]) < 0.3
    assert delivery_level(episode.cues[2]) == 0.5


def test_episode_with_nothing_strong_returns_no_forced_clip():
    quiet = make_episode([(("ANNA (Gentle)" if i % 2 == 0 else "BEN (Warm)"), i * 3.0, i * 3.0 + 2.8, "The weather was pleasant at the market this morning.") for i in range(20)])
    assert candidates_for_episode(quiet, 10).kept == []


def test_blind_transcript_hides_narrative_labels_and_production_words():
    episode = make_episode([
        ("THE EX HUSBAND (Cold)", 0.0, 3.0, "You should not have come."),
        ("LADY ANNA (Furious)", 3.0, 6.0, "Tell me the truth."),
        ("ACTION", 6.0, 8.0, "The Ex Husband grabs Lady Anna by the arm."),
        ("SOUND FX", 8.0, 10.0, "Strings swell to a cliffhanger."),
    ])
    blind = blind_clip(episode, 0.0, 10.0, collect_labels([episode]), pack_name_words([episode]))
    assert "EX HUSBAND" not in blind.text.upper()
    assert "cliffhanger" not in blind.text.lower()
    assert "Cold" not in blind.text
    assert 'SPEAKER A: "You should not have come."' in blind.text  # Spoken words stay exact.
    assert "SPEAKER A grabs SPEAKER B" in blind.text


def test_reaction_alone_is_a_weak_opening():
    reaction = make_episode([("ACTION", 0.0, 2.0, "She gasps and her eyes widen in disbelief.")])
    cause = make_episode([("ACTION", 0.0, 2.0, "He slams the door and grabs her by the arm.")])
    assert hook_signal(reaction, reaction.cues[0]).value < hook_signal(cause, cause.cues[0]).value


def test_short_reply_is_a_weaker_opening_than_the_line_that_started_the_exchange():
    episode = make_episode([("ANNA (Furious)", 3.0, 6.0, "You sold our home to pay your debts!"), ("BEN (Cold)", 6.2, 7.5, "You hear that?")])
    assert hook_signal(episode, episode.cues[1]).value < hook_signal(episode, episode.cues[0]).value


def test_a_moment_that_lands_on_someone_scores_higher():
    landed = make_episode([("ANNA (Cold)", 0.0, 2.0, "The papers are in the desk."), ("BEN (Screaming, Terrified)", 2.2, 4.0, "No!")])
    flat = make_episode([("ANNA (Cold)", 0.0, 2.0, "The papers are in the desk."), ("BEN (Calm)", 2.2, 4.0, "Good.")])
    assert ending_signal(landed, landed.cues[0]).value > ending_signal(flat, flat.cues[0]).value


def test_next_episode_notes_only_confirm_a_final_beat():
    rows = dialogue_rows(0.0, 6)
    episode = make_episode(rows)
    last = episode.cues[-1]
    middle = episode.cues[2]
    notes = "Picks up from the cliffhanger where she confesses."
    assert ending_signal(episode, last, notes).value > ending_signal(episode, last, "Follows the quiet evening.").value
    assert ending_signal(episode, middle, notes).value == ending_signal(episode, middle, "Follows the quiet evening.").value


def test_arrival_counts_as_an_open_ending():
    arrival = make_episode([("ACTION", 0.0, 2.0, "The heavy doors burst open, revealing an armed stranger."), ("ANNA (Calm)", 9.0, 10.0, "Nothing to add.")])
    plain = make_episode([("ACTION", 0.0, 2.0, "She folds the laundry and puts it away."), ("ANNA (Calm)", 9.0, 10.0, "Nothing to add.")])
    assert ending_signal(arrival, arrival.cues[0]).value > ending_signal(plain, plain.cues[0]).value


def test_key_moment_measures_the_writers_summary_without_rewarding_length():
    rows = [("ANNA (Cold)", i * 3.0, i * 3.0 + 2.8, "The harbour lights went out and the ship sank.") for i in range(20)]
    episode = make_episode(rows, logline="Harbour lights fail and a ship sinks.")
    short = build_clip(episode, episode.cues[0], episode.cues[9]).clip
    long = build_clip(episode, episode.cues[0], episode.cues[19]).clip
    assert key_moment_signal(episode, short).value > 0.5
    assert key_moment_signal(episode, long).value <= key_moment_signal(episode, short).value
    other = make_episode(rows, logline="A wedding is cancelled in the mountains.")
    assert key_moment_signal(other, build_clip(other, other.cues[0], other.cues[9]).clip).value == 0


def test_missing_summary_is_neutral():
    episode = make_episode(dialogue_rows(0.0, 12), logline="")
    clip = build_clip(episode, episode.cues[0], episode.cues[10]).clip
    assert key_moment_signal(episode, clip).value == 0.5


def test_understanding_signal_never_reads_the_episode_summary():
    rows = dialogue_rows(0.0, 12)
    one = make_episode(rows, logline="Her husband, her sister and her father betray her.")
    two = make_episode(rows, logline="Nothing relevant.")
    clip_one = build_clip(one, one.cues[0], one.cues[10]).clip
    clip_two = build_clip(two, two.cues[0], two.cues[10]).clip
    assert understanding_signal(one, clip_one).value == understanding_signal(two, clip_two).value
