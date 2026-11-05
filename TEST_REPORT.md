# Test report

Actual results from this project. Everything below was run. Anything not tested is listed in its own section.

## Result

```
python -m pytest
185 passed
```

| Test file | Tests | What it covers |
|---|---:|---|
| `test_parser.py` | 16 | File reading, timestamps, cue and scene extraction, data problems |
| `test_pack_edge_cases.py` | 14 | Broken or unusual input packs |
| `test_boundaries.py` | 24 | Candidate generation, duration, boundaries, situations A to E |
| `test_story_edge_cases.py` | 22 | Story situations that simple rules get wrong |
| `test_llm_client.py` | 26 | Model failures, retries, caching, keys never leaking |
| `test_ai_pipeline.py` | 42 | AI assisted mode from end to end with a stand in provider |
| `test_real_http.py` | 6 | The same pipeline over real HTTP to a local stand in server |
| `test_ranking_outputs_evaluation.py` | 26 | Ranking, duplicates, JSON, CSV, tamper detection, comparisons |
| `test_confidentiality_scan.py` | 4 | The leak scanner finds planted text |
| `test_app.py` | 5 | The interface, run headlessly on the invented sample show |

## Required areas

| Area | Example tests |
|---|---|
| File reading | `test_sample_pack_cues_have_unique_ids`, `test_folder_input_works` |
| Timestamp conversion | `test_timestamp_conversion_both_ways`, `test_invalid_timestamps_return_none` |
| Cue extraction | `test_labels_are_split_without_merging_people`, `test_dialogue_quotes_removed_and_words_unchanged` |
| Scene extraction | `test_uppercase_scene_labels_parse_the_same`, `test_incomplete_scene_is_recorded` |
| Candidate generation | `test_situation_a_valid_35_second_clip`, `test_episode_with_nothing_strong_returns_no_forced_clip` |
| Duration checks | `test_situation_b_too_long_is_rejected_not_trimmed`, `test_situation_c_too_short_is_rejected_not_stretched` |
| Boundary validation | `test_times_always_come_from_cues_and_are_never_invented`, `test_situation_e_end_inside_a_line_moves_to_the_end_of_that_line` |
| Ranking | `test_ranking_prefers_variety_over_one_stretch_of_story` |
| Duplicate removal | `test_duplicates_keep_the_stronger_clip_and_record_the_removal`, `test_short_clip_inside_a_longer_one_counts_as_a_duplicate` |
| JSON validation | `test_schema_rejects_bad_promos`, `test_changed_time_is_caught`, `test_changed_quotation_is_caught` |
| CSV generation | `test_csv_matches_json`, `test_csv_can_be_written_with_no_promos` |

## Required edge cases

### File issues
| Case | Test |
|---|---|
| Empty ZIP | `test_empty_zip_is_a_clear_error` |
| Corrupted ZIP | `test_corrupted_zip_is_a_clear_error` |
| No TXT files | `test_zip_with_no_txt_files` |
| Duplicate episode files | `test_duplicate_episode_files_keep_first_and_report` |
| Missing episode numbers | `test_no_episode_number_anywhere_is_reported_and_not_processed`, `test_number_from_file_name_when_header_is_missing` |
| Unexpected folder structures | `test_unexpected_folder_structure_still_works` |

### Timestamp issues
| Case | Test |
|---|---|
| Missing start | `test_missing_start_is_recorded_not_dropped` |
| Missing end | `test_missing_end_is_recorded` |
| Invalid format | `test_invalid_format_is_recorded` |
| End before start | `test_end_before_start_is_recorded` |
| Overlapping cues | `test_overlap_within_a_track_is_recorded_but_camera_over_dialogue_is_not` |
| Cue beyond the declared duration | `test_cue_beyond_scene_end_is_recorded` |
| Clip shorter than 20 seconds | `test_situation_c_too_short_is_rejected_not_stretched` |
| Clip longer than 60 seconds | `test_situation_b_too_long_is_rejected_not_trimmed` |

### Story issues
| Case | Test |
|---|---|
| Strong dialogue without action | `test_strong_dialogue_without_action_can_hook` |
| Strong action without dialogue | `test_strong_action_without_dialogue_can_hook` |
| A normal question mistaken for a cliffhanger | `test_normal_question_scores_lower_than_tense_question` |
| Dramatic words in ordinary conversation | `test_dramatic_word_in_ordinary_talk_does_not_make_a_strong_hook` |
| An ending that resolves the conflict | `test_ending_that_resolves_the_conflict_is_marked_down`, and the gate test for `ending_resolves_the_conflict` |
| A clip needing too much earlier information | `test_clip_needing_earlier_context_scores_lower_on_understanding` |
| A clip revealing too much | `test_late_story_clips_carry_a_position_penalty` |
| Multiple descriptions of one event | `test_multiple_descriptions_of_one_event_do_not_count_twice` |
| Incorrect character identity assumptions | `test_label_identity_is_not_assumed` |
| The word cliffhanger without real suspense | `test_sound_description_with_the_word_cliffhanger_changes_nothing`, `test_camera_text_with_the_word_cliffhanger_changes_nothing` |

**These tests have limits.** They show Basic's signals move in the right direction on invented examples. They do not show it always gets such cases right on real scripts, and `FAILURE_ANALYSIS.md` lists real cases where it did not. For example, it mistook an ordinary question for a cliffhanger in clip B0017.

### Model issues
All of these ran against a stand in provider, not a real model.

| Case | Test |
|---|---|
| Missing API key | `test_missing_key_is_a_clear_error_and_sends_nothing` |
| Invalid API key | `test_invalid_key_stops_immediately_without_retrying`, `test_wrong_key_over_real_http_is_reported_clearly` |
| Rate limits | `test_rate_limit_waits_and_retries`, `test_rate_limit_stops_the_run_and_resume_finishes_it` |
| Network failure | `test_network_failure_retries_then_reports`, `test_server_that_is_down_gives_a_clear_network_error` |
| Empty model response | `test_empty_response_retries_once_then_fails` |
| Invalid JSON | `test_invalid_json_gets_one_retry_with_a_reminder`, `test_invalid_json_twice_fails_clearly` |
| Unknown cue IDs | `test_unknown_cue_ids_are_rejected_and_recorded` |
| Invented dialogue | `test_invented_dialogue_is_discarded_and_only_the_screenplay_is_used`, `test_evaluate_clip_rejects_invented_evidence` |
| Invented timestamps | `test_invented_timestamps_are_recorded_and_never_used` |
| Scores outside the permitted range | `test_scores_outside_the_range_are_rejected` |
| Different rankings on repeated runs | `test_stability_report_detects_a_different_ranking` |

## Checks on the real 50 episode pack

| Check | Result |
|---|---|
| Files read | 50 of 50, with no pack level problems |
| Cues extracted | 3,727 (1,754 camera, 1,487 dialogue, 372 action, 114 sound) |
| Cues without valid times | 0 |
| Data notes recorded, none removed | 20 small overlaps within a track, and 1 cue slightly past its scene end |
| Basic mode, recommended clips | 19 |
| Every promo checked against the screenplay (times, cue IDs, exact quotes) | 0 errors |
| All clips between 20 and 60 seconds | Yes, 21.8 to 60.0 seconds |
| Repeat run | `promos.json`, `promos.csv` and `report.md` are byte identical |
| Masked transcripts on 257 real clips | No character names found in action or camera text |
| Confidentiality scan of the public code and final ZIP | Clean |

## Interface

`test_app.py` runs the final code with Streamlit's own test tool on the invented sample show. It covers the start page, a Basic run, the clearly labelled results, opening every clip's details, and reopening an earlier run.

An earlier version was also clicked through by hand in a browser, including AI assisted mode with no key, which showed a clear message. Later changes were only covered by the automated test. Clicking the download buttons and uploading a file through the page have not been tested. The parser's handling of the same ZIP files has its own tests.

## Not tested

- **AI assisted mode on a real model.** No real model has ever seen a prompt from this tool. The tests prove the checks and plumbing work. They say nothing about how good a real model's picks would be, and real replies may expose problems a stand in cannot.
- **The stability of AI assisted runs.** The comparison code is tested, but no real runs exist to compare.
- **Basic against AI assisted.** The comparison code is tested, but it has never run on real results.
- **Comparison with human picks.** The candidate has not filled in the manual reference sheet.
- **Time saved.** Manual discovery time has not been measured.
- **Any real audience or ad performance.**
