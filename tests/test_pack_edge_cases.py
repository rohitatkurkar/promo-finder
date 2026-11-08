"""Problems with the input pack itself."""

import zipfile

import pytest
from conftest import make_episode  # noqa: F401
from make_sample import EPISODE_1, EPISODE_3, episode_text

from promo_finder.parser import ScreenplayPackError, load_pack

GOOD_TEXT = episode_text(1, "log", "notes", EPISODE_1)


def _zip(path, files):
    with zipfile.ZipFile(path, "w") as archive:
        for name, text in files.items():
            archive.writestr(name, text)
    return path


def test_empty_zip_is_a_clear_error(tmp_path):
    with pytest.raises(ScreenplayPackError, match="No screenplay"):
        load_pack(_zip(tmp_path / "empty.zip", {}))


def test_corrupted_zip_is_a_clear_error(tmp_path):
    path = tmp_path / "broken.zip"
    path.write_bytes(b"this is not a zip file at all")
    with pytest.raises(ScreenplayPackError, match="Not a valid ZIP"):
        load_pack(path)


def test_zip_with_no_txt_files(tmp_path):
    with pytest.raises(ScreenplayPackError, match="No screenplay"):
        load_pack(_zip(tmp_path / "no_txt.zip", {"notes.pdf": "x", "poster.png": "y"}))


def test_missing_input_path(tmp_path):
    with pytest.raises(ScreenplayPackError, match="not found"):
        load_pack(tmp_path / "nothing_here.zip")


def test_non_txt_files_are_reported(tmp_path):
    episodes, issues = load_pack(_zip(tmp_path / "mixed.zip", {"episode-001.txt": GOOD_TEXT, "cover.png": "x"}))
    assert len(episodes) == 1
    assert any(issue.issue_type == "ignored_non_txt_file" for issue in issues)


def test_duplicate_episode_files_keep_first_and_report(tmp_path):
    changed = GOOD_TEXT.replace("log", "different log", 1)
    episodes, issues = load_pack(_zip(tmp_path / "dup.zip", {"a/episode-001.txt": GOOD_TEXT, "b/episode-001.txt": changed}))
    assert len(episodes) == 1
    duplicates = [issue for issue in issues if issue.issue_type == "duplicate_episode"]
    assert duplicates and "DIFFERENT" in duplicates[0].detail


def test_no_episode_number_anywhere_is_reported_and_not_processed(tmp_path):
    text = GOOD_TEXT.replace("EPISODE NUMBER: Episode 1\n", "")
    episodes, issues = load_pack(_zip(tmp_path / "num.zip", {"episode-001.txt": GOOD_TEXT, "script.txt": text}))
    assert [episode.number for episode in episodes] == [1]
    assert any(issue.issue_type == "unusable_episode" for issue in issues)


def test_all_files_unusable_is_a_clear_error(tmp_path):
    text = GOOD_TEXT.replace("EPISODE NUMBER: Episode 1\n", "")
    with pytest.raises(ScreenplayPackError, match="none could be used"):
        load_pack(_zip(tmp_path / "bad.zip", {"script.txt": text}))


def test_number_from_file_name_when_header_is_missing(tmp_path):
    text = GOOD_TEXT.replace("EPISODE NUMBER: Episode 1\n", "")
    episodes, _ = load_pack(_zip(tmp_path / "num.zip", {"episode-007-x.txt": text}))
    assert episodes[0].number == 7
    assert any(issue.issue_type == "missing_episode_number" for issue in episodes[0].issues)


def test_header_and_file_name_disagree_is_recorded(tmp_path):
    episodes, _ = load_pack(_zip(tmp_path / "num.zip", {"episode-009.txt": GOOD_TEXT}))
    assert episodes[0].number == 1
    assert any(issue.issue_type == "episode_number_mismatch" for issue in episodes[0].issues)


def test_gaps_in_episode_numbers_are_reported(tmp_path):
    third = episode_text(3, "log", "notes", EPISODE_3)
    _, issues = load_pack(_zip(tmp_path / "gap.zip", {"episode-001.txt": GOOD_TEXT, "episode-003.txt": third}))
    assert any(issue.issue_type == "missing_episodes" and "2" in issue.detail for issue in issues)


def test_unexpected_folder_structure_still_works(tmp_path):
    episodes, _ = load_pack(_zip(tmp_path / "deep.zip", {"x/y/z/episode-001.txt": GOOD_TEXT}))
    assert [episode.number for episode in episodes] == [1]


def test_macos_metadata_files_are_ignored(tmp_path):
    episodes, issues = load_pack(_zip(tmp_path / "mac.zip", {
        "episode-001.txt": GOOD_TEXT, "__MACOSX/._episode-001.txt": "junk", ".DS_Store": "junk",
    }))
    assert len(episodes) == 1 and issues == []


def test_folder_input_works(tmp_path):
    folder = tmp_path / "show"
    (folder / "sub").mkdir(parents=True)
    (folder / "sub" / "episode-001.txt").write_text(GOOD_TEXT, encoding="utf-8")
    episodes = load_pack(folder)[0]
    assert len(episodes) == 1
    # The same name on Windows and macOS, so result files do not depend on the platform.
    assert episodes[0].file_name == "sub/episode-001.txt"
