"""The scanner must catch real leaks, including text inside Python lists."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from check_confidentiality import scan  # noqa: E402


def test_clean_folder_passes(sample_zip, tmp_path):
    folder = tmp_path / "public"
    folder.mkdir()
    (folder / "notes.md").write_text("Nothing from the show is in here.", encoding="utf-8")
    assert scan(sample_zip, folder) == []


def test_planted_line_is_found_even_inside_a_python_list(sample_zip, tmp_path):
    folder = tmp_path / "public"
    folder.mkdir()
    (folder / "code.py").write_text('ROWS = ["You sank that ship and let your own brother drown!"]\n', encoding="utf-8")
    assert any("screenplay line" in problem for problem in scan(sample_zip, folder))


def test_planted_character_name_and_title_are_found(sample_zip, tmp_path):
    folder = tmp_path / "public"
    folder.mkdir()
    (folder / "notes.md").write_text("In The Lighthouse Debt, Tomas walks home.", encoding="utf-8")
    problems = scan(sample_zip, folder)
    assert any("title" in problem for problem in problems)
    assert any("tomas" in problem for problem in problems)


def test_finished_zip_can_be_scanned(sample_zip, tmp_path):
    import zipfile

    archive_path = tmp_path / "out.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("x/notes.md", "Tomas again.")
    assert scan(sample_zip, archive_path)
