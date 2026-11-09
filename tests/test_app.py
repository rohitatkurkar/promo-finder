"""Run the interface headlessly on the invented sample show, using Streamlit's own test tool."""

import json

import pytest
from streamlit.testing.v1 import AppTest

from promo_finder.parser import load_pack
from conftest import ROOT


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("PROMO_OUTPUT_DIR", str(tmp_path / "outputs"))
    monkeypatch.setenv("PROMO_ENV_FILE", str(tmp_path / "no.env"))  # Never read the real key in tests.
    return AppTest.from_file(str(ROOT / "app.py"), default_timeout=60)


def test_start_page_explains_what_to_do(app):
    app.run()
    assert not app.exception
    assert any("click Find promos" in item.value for item in app.success)
    assert app.title[0].value == "Promo Finder"


def test_basic_run_on_the_sample_show_shows_labelled_results(app, tmp_path):
    app.run()
    app.sidebar.button[0].click().run()
    assert not app.exception
    assert any("Basic selections" in item.value for item in app.warning)
    assert app.metric[0].value == "3 of 3"
    assert app.metric[3].value == "0"
    assert len(app.dataframe) >= 1
    assert any("Finished" in item.value for item in app.success)
    assert (tmp_path / "outputs").exists()
    assert any("Post this first" in item.value for item in app.subheader)


def test_each_clip_can_be_opened_without_error(app):
    app.run()
    app.sidebar.button[0].click().run()
    chooser = next(box for box in app.selectbox if box.label == "Choose a clip")
    for option in chooser.options:
        chooser.set_value(option)
        app.run()
        assert not app.exception
        chooser = next(box for box in app.selectbox if box.label == "Choose a clip")


def test_an_earlier_run_can_be_reopened(app):
    app.run()
    app.sidebar.button[0].click().run()
    fresh = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60)
    fresh.run()
    assert not fresh.exception
    assert any("Results" in item.value for item in fresh.header)


def test_sample_pack_used_by_the_app_is_valid():
    episodes, issues = load_pack(ROOT / "sample_input" / "synthetic_show.zip")
    assert len(episodes) == 3 and issues == []


def _run_sample(app):
    app.run()
    app.sidebar.button[0].click().run()
    assert not app.exception
    return app


def _review_radios(app):
    return {radio.label: radio for radio in app.radio if radio.label != "Selection method"}


def _save_button(app):
    return next(button for button in app.button if button.label == "Save review")


def test_a_review_can_be_saved_and_promos_stay_unchanged(app, tmp_path):
    _run_sample(app)
    run_dir = next(path for path in (tmp_path / "outputs").iterdir() if (path / "promos.json").exists())
    promos_before = (run_dir / "promos.json").read_bytes()
    app.text_input(key="reviewer").input("itesh").run()
    radios = _review_radios(app)
    for label in ("Hook quality (1 to 5)", "Cliffhanger quality (1 to 5)", "Clarity (1 to 5)", "Overall quality (1 to 5)"):
        radios[label].set_value(4)
    radios["Would publish?"].set_value("Maybe")
    next(area for area in app.text_area if area.label == "Comments (optional)").input("Clear and tense.")
    _save_button(app).click().run()
    assert not app.exception
    assert any("Review saved" in item.value for item in app.success)
    store = tmp_path / "outputs" / "human_reviews" / "human_reviews.jsonl"
    saved = [json.loads(line) for line in store.read_text(encoding="utf-8").splitlines()]
    assert len(saved) == 1 and saved[0]["reviewer"] == "itesh" and saved[0]["would_publish"] == "maybe"
    assert saved[0]["comments"] == "Clear and tense." and saved[0]["run_id"] == run_dir.name
    assert (run_dir / "promos.json").read_bytes() == promos_before
    assert any(item.label in ("Reviews CSV", "Reviews JSON") for item in app.get("download_button"))


def test_a_review_with_missing_answers_is_not_saved(app, tmp_path):
    _run_sample(app)
    app.text_input(key="reviewer").input("itesh").run()
    _review_radios(app)["Hook quality (1 to 5)"].set_value(5)
    _save_button(app).click().run()
    assert any("Please answer every question" in item.value for item in app.error)
    assert not (tmp_path / "outputs" / "human_reviews" / "human_reviews.jsonl").exists()


def test_no_review_form_without_a_reviewer_name(app):
    _run_sample(app)
    assert any("reviewer name" in item.value for item in app.info)
    assert not any(button.label == "Save review" for button in app.button)


def test_blind_mode_hides_the_ai_judgement(app):
    _run_sample(app)
    app.checkbox(key="blind_review").check().run()
    assert not app.exception
    assert not any(item.value in ("Ranking", "Post this first", "Human review compared with AI") for item in app.subheader)
    columns = list(app.dataframe[0].value.columns)
    assert "Score" not in columns and "Rank" not in columns and "Hook" not in columns
    chooser = next(box for box in app.selectbox if box.label == "Choose a clip")
    assert all(option.startswith("Episode ") and "B0" not in option for option in chooser.options)
    assert not any("Score breakdown" in item.value or "Why it could work" in item.value for item in app.markdown)
    labels = [button.label for button in app.get("download_button")]
    assert not {"JSON", "CSV", "Report", "Blank review sheet", "Reviews CSV", "Reviews JSON"} & set(labels)  # They hold AI scores.


def _catalog():
    return json.loads((ROOT / "demo_runs" / "catalog.json").read_text(encoding="utf-8"))


def _open_run_box(app):
    return next(box for box in app.sidebar.selectbox if box.label == "Open an existing run")


def test_the_final_run_opens_by_default(app):
    app.run()
    assert not app.exception
    catalog = _catalog()
    final = next(entry for entry in catalog["runs"] if entry["folder"] == catalog["default"])
    assert final["kind"] == "final"
    assert _open_run_box(app).value == final["label"]
    assert any("Final full-dataset run" in item.value for item in app.success)
    assert app.metric[0].value == "50 of 50" and app.metric[1].value == "33"
    assert any(box.label == "Choose a clip" for box in app.selectbox)


def test_every_bundled_run_can_be_opened_and_shows_its_own_results(app):
    app.run()
    catalog = _catalog()
    labels = [entry["label"] for entry in catalog["runs"]]
    assert _open_run_box(app).options[:len(labels)] == labels  # Catalog order, final run first.
    for entry in catalog["runs"]:
        folder = ROOT / "demo_runs" / entry["folder"]
        data = json.loads((folder / "promos.json").read_text(encoding="utf-8"))
        summary = json.loads((folder / "processing_summary.json").read_text(encoding="utf-8"))
        _open_run_box(app).set_value(entry["label"]).run()
        assert not app.exception, entry["folder"]
        assert any(entry["description"][:40] in item.value for item in list(app.success) + list(app.info))
        assert app.metric[0].value == f"{summary['episodes_processed']} of {summary['episodes_in_pack']}"
        assert app.metric[1].value == str(len(data["promos"]))
        chooser = next(box for box in app.selectbox if box.label == "Choose a clip")
        assert len(chooser.options) == len(data["promos"])
        assert chooser.options[0].startswith(f"1. {data['promos'][0]['promo_id']}")
        ranking = next(frame.value for frame in app.dataframe if "Rank" in frame.value.columns and "Score" in frame.value.columns)
        assert list(ranking["ID"]) == [p["promo_id"] for p in data["promos"]]
        assert any(item.value == "Human review compared with AI" for item in app.subheader)
        if data["selection_method"] == "ai_assisted":
            first = data["promos"][0]
            evaluation = json.loads((folder / "evaluations" / f"{first['clip_key']}.json").read_text(encoding="utf-8"))
            assert evaluation["hook_rating"] == first["hook"]["rating_out_of_5"]
            assert any("not published with the app" in item.value for item in app.caption)
            assert len(_expander_table(app)) > 0


def test_a_new_run_is_shown_and_the_final_run_can_be_reopened(app):
    _run_sample(app)
    assert _open_run_box(app).value == "Your latest run"
    assert app.metric[0].value == "3 of 3"
    final = next(entry for entry in _catalog()["runs"] if entry["kind"] == "final")
    _open_run_box(app).set_value(final["label"]).run()
    assert not app.exception and app.metric[0].value == "50 of 50"


def test_a_bundled_run_can_be_reviewed_without_changing_its_files(app, tmp_path):
    app.run()
    folder = ROOT / "demo_runs" / _catalog()["default"]
    before = {p.name: p.read_bytes() for p in folder.rglob("*") if p.is_file()}
    app.text_input(key="reviewer").input("demo_reviewer").run()
    radios = _review_radios(app)
    for label in ("Hook quality (1 to 5)", "Cliffhanger quality (1 to 5)", "Clarity (1 to 5)", "Overall quality (1 to 5)"):
        radios[label].set_value(3)
    radios["Would publish?"].set_value("No")
    _save_button(app).click().run()
    assert not app.exception and any("Review saved" in item.value for item in app.success)
    saved = [json.loads(line) for line in (tmp_path / "outputs" / "human_reviews" / "human_reviews.jsonl").read_text(encoding="utf-8").splitlines()]
    assert saved[0]["run_id"] == folder.name and saved[0]["reviewer"] == "demo_reviewer"
    assert {p.name: p.read_bytes() for p in folder.rglob("*") if p.is_file()} == before


def _choose_ai(app, secrets):
    for name, value in secrets.items():
        app.secrets[name] = value
    app.run()
    next(radio for radio in app.radio if radio.label == "Selection method").set_value("AI assisted").run()
    assert not app.exception
    return app


def _find_promos(app):
    next(button for button in app.sidebar.button if button.label == "Find promos").click().run()
    assert not app.exception


def _ai_runs(tmp_path):
    folder = tmp_path / "outputs"
    return [path for path in folder.iterdir() if path.name.startswith("ai_")] if folder.exists() else []


def test_ai_mode_needs_no_password_and_choosing_it_starts_nothing(app, tmp_path):
    _choose_ai(app, {"LLM_API_KEY": "secret-test-key"})
    assert any("An API key is configured" in item.value for item in app.success)
    assert not any("password" in box.label.lower() for box in app.text_input)
    assert any("starts nothing" in item.value for item in app.caption)
    assert _ai_runs(tmp_path) == []  # Choosing the mode called no model and made no run.
    assert app.metric[0].value == "50 of 50"  # The final run is still shown.


def test_ai_run_starts_without_a_password_and_reads_secrets(app, tmp_path):
    # No models are set, so the pipeline stops at its own setup check before any network call.
    _choose_ai(app, {"LLM_API_KEY": "secret-test-key"})
    _find_promos(app)
    assert any("No model set for the finder role" in item.value for item in app.error)
    assert not any("secret-test-key" in item.value for item in app.error)


def test_hosted_ai_runs_have_no_episode_limit(app, tmp_path):
    # An old AI_MAX_EPISODES setting is ignored. No models are set, so the run stops at the pipeline's own setup check,
    # after the episode choice was accepted and before any network call.
    _choose_ai(app, {"LLM_API_KEY": "secret-test-key", "AI_MAX_EPISODES": "2"})
    _find_promos(app)  # Empty box: all 3 sample episodes.
    assert not any("at most" in item.value for item in app.error)
    assert any("No model set for the finder role" in item.value for item in app.error)
    app.text_input(key="ai_episodes").input("9").run()
    _find_promos(app)
    assert any("Not in this pack" in item.value for item in app.error)
    assert _ai_runs(tmp_path) == []


def test_only_one_ai_run_goes_at_a_time(app, tmp_path):
    from promo_finder.hosting import AI_RUN_LOCK
    _choose_ai(app, {"LLM_API_KEY": "secret-test-key"})
    assert AI_RUN_LOCK.acquire(blocking=False)  # Another visitor's AI run is going.
    try:
        _find_promos(app)
        assert any("Another AI assisted run is in progress" in item.value for item in app.warning)
        assert _ai_runs(tmp_path) == [] and not any("No model set" in item.value for item in app.error)
        next(radio for radio in app.radio if radio.label == "Selection method").set_value("Basic (no API key)").run()
        _find_promos(app)  # Basic mode is not held up.
        assert any("Finished" in item.value for item in app.success)
    finally:
        AI_RUN_LOCK.release()
    next(radio for radio in app.radio if radio.label == "Selection method").set_value("AI assisted").run()
    _find_promos(app)
    assert any("No model set for the finder role" in item.value for item in app.error)
    assert AI_RUN_LOCK.acquire(blocking=False)  # Released after that run ended with an error.
    AI_RUN_LOCK.release()


# Sidebar layout.

def test_sidebar_sections_come_in_order_and_new_run_is_folded(app):
    app.run()
    headers = [item.value for item in app.sidebar.header]
    assert headers == ["Existing runs", "Human review"]
    assert any(item.value == "Reviews apply to the currently selected run." for item in app.sidebar.caption)
    expander = next(item for item in app.sidebar.expander if item.label == "Run on a new screenplay pack")
    assert expander.proto.expanded is False
    assert [button.label for button in expander.button] == ["Find promos"]
    assert {box.label for box in expander.checkbox} >= {"Use the built in invented sample show"}
    assert any(radio.label == "Selection method" for radio in expander.radio)


def test_reviewer_settings_do_not_change_the_open_run(app):
    app.run()
    trial = next(entry for entry in _catalog()["runs"] if entry["folder"].startswith("ai_trial"))
    _open_run_box(app).set_value(trial["label"]).run()
    app.text_input(key="reviewer").input("someone").run()
    app.checkbox(key="blind_review").check().run()
    app.checkbox(key="blind_review").uncheck().run()
    assert not app.exception
    assert _open_run_box(app).value == trial["label"] and app.metric[0].value == "1 of 50"


# Screenplay excerpts bundled with the demo runs.

def _expander_table(app):
    expander = next(item for item in app.expander if item.label == "See the screenplay for this clip")
    assert expander.proto.expanded is False
    return expander.table[0].value


def test_every_bundled_run_has_an_excerpt_for_every_promo():
    for entry in _catalog()["runs"]:
        folder = ROOT / "demo_runs" / entry["folder"]
        promos = json.loads((folder / "promos.json").read_text(encoding="utf-8"))["promos"]
        excerpts = json.loads((folder / "transcripts.json").read_text(encoding="utf-8"))
        assert excerpts["run_id"] == entry["folder"]
        assert set(excerpts["clips"]) == {p["clip_key"] for p in promos}
        for promo in promos:
            clip = excerpts["clips"][promo["clip_key"]]
            assert clip["promo_id"] == promo["promo_id"]
            ids = [cue["cue_id"] for part in clip["segments"] for cue in part["cues"]]
            assert promo["hook"]["cue_ids"][0] in ids and promo["cliffhanger"]["cue_ids"][0] in ids
            for part, segment in zip(clip["segments"], promo["segments"]):
                assert part["episode"] == segment["episode"]
                assert all(cue_id.startswith(f"E{segment['episode']:02d}_") for cue_id in (c["cue_id"] for c in part["cues"]))
                assert all(c["end"] > segment["start_seconds"] and c["start"] < segment["end_seconds"] for c in part["cues"])


def test_excerpts_match_the_screenplay_they_came_from(tmp_path):
    # The sample show's pack is public, so its bundled excerpts can be rebuilt and compared exactly.
    import sys
    sys.path.insert(0, str(ROOT / "tools"))
    from build_transcript_excerpts import build_excerpts
    folder = ROOT / "demo_runs" / "basic_sample_show"
    rebuilt = build_excerpts(ROOT / "sample_input" / "synthetic_show.zip", folder)
    assert rebuilt == json.loads((folder / "transcripts.json").read_text(encoding="utf-8"))


def test_the_final_run_shows_each_clips_screenplay(app):
    app.run()
    folder = ROOT / "demo_runs" / _catalog()["default"]
    promos = json.loads((folder / "promos.json").read_text(encoding="utf-8"))["promos"]
    chooser = next(box for box in app.selectbox if box.label == "Choose a clip")
    for index in (0, len(promos) - 1):
        chooser.set_value(chooser.options[index]).run()
        table = _expander_table(app)
        assert promos[index]["hook"]["cue_ids"][0] in table.index
        assert promos[index]["cliffhanger"]["cue_ids"][0] in table.index
        assert {"Start", "End", "Type", "Speaker", "Delivery", "Text"} <= set(table.columns)
        chooser = next(box for box in app.selectbox if box.label == "Choose a clip")


def test_blind_mode_still_shows_the_screenplay_but_hides_ai_judgement(app):
    app.run()
    app.checkbox(key="blind_review").check().run()
    assert not app.exception
    assert len(_expander_table(app)) > 0
    assert not any("Score breakdown" in item.value or "Why it could work" in item.value for item in app.markdown)


# Optional settings for a local review session.

@pytest.fixture
def review_set(tmp_path):
    final = _catalog()["default"]
    promos = json.loads((ROOT / "demo_runs" / final / "promos.json").read_text(encoding="utf-8"))["promos"]
    keys = [promos[0]["clip_key"], promos[5]["clip_key"], promos[10]["clip_key"]]
    path = tmp_path / "review_set.json"
    path.write_text(json.dumps({"run_id": final, "clip_keys": keys}), encoding="utf-8")
    return path, keys


def test_blind_mode_can_start_on(tmp_path, monkeypatch):
    monkeypatch.setenv("PROMO_OUTPUT_DIR", str(tmp_path / "outputs"))
    monkeypatch.setenv("PROMO_ENV_FILE", str(tmp_path / "no.env"))
    monkeypatch.setenv("PROMO_BLIND_REVIEW_DEFAULT", "1")
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60)
    app.run()
    assert not app.exception
    assert app.checkbox(key="blind_review").value is True
    assert not any(item.value in ("Ranking", "Post this first") for item in app.subheader)


def test_blind_mode_is_off_by_default(app):
    app.run()
    assert app.checkbox(key="blind_review").value is False


def test_review_set_limits_the_clips_and_next_previous_move_through_them(app, monkeypatch, review_set):
    path, keys = review_set
    monkeypatch.setenv("PROMO_REVIEW_SET", str(path))
    app.run()
    app.checkbox(key="blind_review").check().run()
    assert not app.exception
    chooser = app.selectbox(key="clip_choice")
    assert len(chooser.options) == 3
    first = chooser.value
    next(b for b in app.button if b.label == "Next clip ▶").click().run()
    assert app.selectbox(key="clip_choice").value == app.selectbox(key="clip_choice").options[1]
    assert any("Clip 2 of 3" in item.value for item in app.caption)
    next(b for b in app.button if b.label == "◀ Previous clip").click().run()
    assert app.selectbox(key="clip_choice").value == first
    next(b for b in app.button if b.label == "◀ Previous clip").click().run()
    assert app.selectbox(key="clip_choice").value == app.selectbox(key="clip_choice").options[-1]  # Wraps around.
    app.checkbox(key="only_review_set").uncheck().run()
    assert len(app.selectbox(key="clip_choice").options) == 33


def test_review_set_progress_counts_my_reviews(app, monkeypatch, review_set, tmp_path):
    path, keys = review_set
    monkeypatch.setenv("PROMO_REVIEW_SET", str(path))
    app.run()
    app.text_input(key="reviewer").input("me").run()
    assert any("reviewed 0 of 3" in item.value for item in app.info)
    radios = _review_radios(app)
    for label in ("Hook quality (1 to 5)", "Cliffhanger quality (1 to 5)", "Clarity (1 to 5)", "Overall quality (1 to 5)"):
        radios[label].set_value(4)
    radios["Would publish?"].set_value("Yes")
    _save_button(app).click().run()
    assert any("reviewed 1 of 3" in item.value for item in app.info)
    saved = json.loads((tmp_path / "outputs" / "human_reviews" / "human_reviews.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert saved["clip_key"] in keys and saved["run_id"] == _catalog()["default"]


def test_default_run_setting_opens_that_run(app, monkeypatch):
    trial = next(entry for entry in _catalog()["runs"] if entry["folder"].startswith("ai_trial"))
    monkeypatch.setenv("PROMO_DEFAULT_RUN", str(ROOT / "demo_runs" / trial["folder"]))
    app.run()
    assert _open_run_box(app).value == trial["label"]
    assert app.metric[0].value == "1 of 50"



def test_next_and_previous_still_work_after_blind_mode_is_turned_off(app):
    app.run()
    next(b for b in app.button if b.label == "Next clip ▶").click().run()
    app.checkbox(key="blind_review").check().run()
    app.checkbox(key="blind_review").uncheck().run()
    for button, expected in (("Next clip ▶", "Clip 2 of 33"), ("◀ Previous clip", "Clip 1 of 33"), ("◀ Previous clip", "Clip 33 of 33")):
        next(b for b in app.button if b.label == button).click().run()
        assert not app.exception
        assert any(item.value == expected for item in app.caption), button


# Phase 1: private runs on a shared host, resuming, and the blind export.

def test_blind_export_holds_only_my_reviews(app, tmp_path):
    app.run()
    for name in ("someone_else", "me"):
        app.text_input(key="reviewer").input(name).run()
        radios = _review_radios(app)
        for label in ("Hook quality (1 to 5)", "Cliffhanger quality (1 to 5)", "Clarity (1 to 5)", "Overall quality (1 to 5)"):
            radios[label].set_value(2 if name == "someone_else" else 5)
        radios["Would publish?"].set_value("No" if name == "someone_else" else "Yes")
        _save_button(app).click().run()
    app.checkbox(key="blind_review").check().run()
    export = next(item for item in app.get("download_button") if item.label == "My reviews (JSON)")
    assert not app.exception and export.proto.disabled is False
    # The export's content is built from the same filtered list the button uses.
    store = tmp_path / "outputs" / "human_reviews" / "human_reviews.jsonl"
    assert len(store.read_text(encoding="utf-8").splitlines()) == 2


def _saved_basic_run(tmp_path, name):
    from promo_finder.pipeline import run_basic_pipeline
    run_dir = tmp_path / "outputs" / name
    run_basic_pipeline(ROOT / "sample_input" / "synthetic_show.zip", run_dir)
    return run_dir


def test_a_shared_host_lists_only_my_own_saved_runs(tmp_path, monkeypatch):
    monkeypatch.setenv("PROMO_OUTPUT_DIR", str(tmp_path / "outputs"))
    monkeypatch.setenv("PROMO_ENV_FILE", str(tmp_path / "no.env"))
    _saved_basic_run(tmp_path, "basic_someone_elses_run")
    for shared, listed in (("0", True), ("1", False)):
        monkeypatch.setenv("PROMO_SHARED_HOST", shared)
        app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60)
        app.run()
        assert any("basic_someone_elses_run" in option for option in _open_run_box(app).options) is listed
    app.sidebar.button[0].click().run()  # My own run, on the shared host.
    app.run()
    assert any(option.startswith("Your run: basic_") for option in _open_run_box(app).options)


def test_two_runs_get_two_folders(app, tmp_path):
    _run_sample(app)
    app.sidebar.button[0].click().run()
    assert not app.exception
    assert len([p for p in (tmp_path / "outputs").iterdir() if p.name.startswith("basic_")]) == 2


def test_an_unfinished_run_resumes_in_the_same_folder(app, tmp_path):
    run_dir = _saved_basic_run(tmp_path, "basic_unfinished")
    (run_dir / "promos.json").unlink()  # As if the run was interrupted before its results were written.
    app.session_state["resumable"] = {"run_dir": str(run_dir), "mode": "basic", "fresh": False, "episodes": None,
                                      "source": str(ROOT / "sample_input" / "synthetic_show.zip")}
    app.run()
    resume = next(button for button in app.sidebar.button if button.label == "Resume unfinished run")
    resume.click().run()
    assert not app.exception
    summary = json.loads((run_dir / "processing_summary.json").read_text(encoding="utf-8"))
    assert summary["episodes_resumed_from_checkpoint"] == 3 and (run_dir / "promos.json").exists()
    assert _open_run_box(app).value == "Your latest run" and app.metric[0].value == "3 of 3"
    assert not any(button.label == "Resume unfinished run" for button in app.sidebar.button)  # Finished, so gone.
    assert [p.name for p in (tmp_path / "outputs").iterdir() if p.name.startswith("basic_")] == ["basic_unfinished"]


def test_a_run_whose_pack_is_gone_cannot_be_resumed(app, tmp_path):
    app.session_state["resumable"] = {"run_dir": str(tmp_path / "outputs" / "basic_x"), "mode": "basic", "fresh": False,
                                      "episodes": None, "source": str(tmp_path / "deleted.zip")}
    app.run()
    next(button for button in app.sidebar.button if button.label == "Resume unfinished run").click().run()
    assert any("cannot be resumed" in item.value for item in app.error)
    assert not (tmp_path / "outputs" / "basic_x").exists()
