"""Run the interface headlessly on the invented sample show, using Streamlit's own test tool."""

import pytest
from streamlit.testing.v1 import AppTest

from promo_finder.parser import load_pack
from conftest import ROOT


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("PROMO_OUTPUT_DIR", str(tmp_path / "outputs"))
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
