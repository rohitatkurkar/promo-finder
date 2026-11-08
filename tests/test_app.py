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
    assert any("Find promos" in item.value for item in app.info)
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


def test_the_bundled_demo_shows_before_any_run(app):
    app.run()
    assert not app.exception
    assert any("precomputed demo" in item.value for item in app.info)
    assert any("Results" in item.value for item in app.header)
    assert any(box.label == "Choose a clip" for box in app.selectbox)


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


def test_hosted_key_without_password_keeps_ai_off(app, tmp_path):
    _choose_ai(app, {"LLM_API_KEY": "secret-test-key"})
    assert any("An API key is configured" in item.value for item in app.success)
    assert any("switched off" in item.value for item in app.info)
    _find_promos(app)
    assert any("AI assisted run not started" in item.value for item in app.error)
    assert _ai_runs(tmp_path) == []


def test_wrong_or_missing_password_starts_nothing(app, tmp_path):
    _choose_ai(app, {"LLM_API_KEY": "secret-test-key", "AI_ACCESS_PASSWORD": "right-password"})
    _find_promos(app)
    assert any("Enter the AI access password" in item.value for item in app.error)
    app.text_input(key="ai_password").input("wrong-password").run()
    _find_promos(app)
    assert any("Incorrect AI access password" in item.value for item in app.error)
    assert _ai_runs(tmp_path) == []


def test_correct_password_passes_the_gate_and_reads_secrets(app, tmp_path):
    # No models are set, so the pipeline stops at its own setup check before any network call.
    _choose_ai(app, {"LLM_API_KEY": "secret-test-key", "AI_ACCESS_PASSWORD": "right-password"})
    app.text_input(key="ai_password").input("right-password").run()
    assert any("unlocked" in item.value for item in app.success)
    _find_promos(app)
    assert any("No model set for the finder role" in item.value for item in app.error)
    assert not any("secret-test-key" in item.value for item in app.error)


def test_hosted_ai_runs_are_limited_in_episodes(app, tmp_path):
    _choose_ai(app, {"LLM_API_KEY": "secret-test-key", "AI_ACCESS_PASSWORD": "pw", "AI_MAX_EPISODES": "2",
                     "FINDER_MODEL": "m1", "EVALUATOR_MODEL": "m2"})
    app.text_input(key="ai_password").input("pw").run()
    _find_promos(app)  # Empty box means all 3 sample episodes, over the limit of 2.
    assert any("at most 2 episode(s)" in item.value for item in app.error)
    app.text_input(key="ai_episodes").input("9").run()
    _find_promos(app)
    assert any("Not in this pack" in item.value for item in app.error)
    assert _ai_runs(tmp_path) == []
