"""Uploaded packs are stored once per content and cleaned up; run folders never collide; ZIP limits hold."""

import io
import os
import zipfile

import pytest

from promo_finder import parser
from promo_finder.parser import ScreenplayPackError, load_pack
from promo_finder.uploads import KEEP_UPLOADS_SECONDS, new_run_dir, store_upload
from conftest import ROOT

SAMPLE = ROOT / "sample_input" / "synthetic_show.zip"


def test_the_same_upload_is_written_once(tmp_path):
    data = SAMPLE.read_bytes()
    first = store_upload(data, "show.zip", tmp_path)
    written = first.stat().st_mtime_ns
    again = store_upload(data, "show.zip", tmp_path)
    assert again == first and first.read_bytes() == data
    assert first.stat().st_mtime_ns == written  # Not rewritten on a page refresh.
    assert len(list(tmp_path.iterdir())) == 1
    assert store_upload(data + b" ", "show.zip", tmp_path).parent != first.parent  # Other content, other folder.


def test_old_uploads_are_removed_and_ones_in_use_are_kept(tmp_path):
    old = store_upload(b"old pack", "old.zip", tmp_path)
    used = store_upload(b"pack in use", "used.zip", tmp_path)
    stale = os.stat(old.parent).st_mtime - KEEP_UPLOADS_SECONDS - 10
    os.utime(old.parent, (stale, stale))
    os.utime(used.parent, (stale, stale))
    store_upload(b"pack in use", "used.zip", tmp_path)  # Opening it again marks it as in use.
    store_upload(b"new pack", "new.zip", tmp_path)
    assert not old.exists() and used.exists()


def test_a_crafted_file_name_stays_inside_the_upload_folder(tmp_path):
    path = store_upload(b"x", "../../outside.zip", tmp_path / "uploads")
    assert path.parent.parent == tmp_path / "uploads" and path.name == "outside.zip"


def test_run_folders_started_in_the_same_second_differ(tmp_path):
    names = {new_run_dir(tmp_path, "basic").name for _ in range(50)}
    assert len(names) == 50 and all(name.startswith("basic_") for name in names)


def _zip(tmp_path, files: dict[str, bytes]):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    path = tmp_path / "pack.zip"
    path.write_bytes(buffer.getvalue())
    return path


def test_the_real_sized_sample_pack_is_within_the_limits():
    episodes, _ = load_pack(SAMPLE)
    assert len(episodes) == 3


@pytest.mark.parametrize("limit, value, files, message", [
    ("MAX_ZIP_MEMBERS", 3, {f"Episode {n}.txt": b"x" for n in range(1, 5)}, "holds 4 files"),
    ("MAX_MEMBER_BYTES", 1000, {"Episode 1.txt": b"x" * 1001}, "per file"),
    ("MAX_TOTAL_BYTES", 1500, {"Episode 1.txt": b"x" * 800, "Episode 2.txt": b"x" * 800}, "unpacks to"),
])
def test_oversized_zips_are_refused_before_unpacking(tmp_path, monkeypatch, limit, value, files, message):
    monkeypatch.setattr(parser, limit, value)
    with pytest.raises(ScreenplayPackError, match=message):
        load_pack(_zip(tmp_path, files))
