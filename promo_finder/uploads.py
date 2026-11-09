"""Where the interface keeps uploaded packs and new runs.

An upload is written once per content, not once per page refresh, and old uploads are removed,
so screenplay copies do not pile up on the computer (or host) running the app.
"""

from __future__ import annotations

import hashlib
import os
import secrets
import shutil
import time
from pathlib import Path

UPLOAD_FOLDER_PREFIX = "promo_upload_"
KEEP_UPLOADS_SECONDS = 24 * 60 * 60  # Long enough to finish or resume a run on the same pack.


def store_upload(data: bytes, file_name: str, root: str | Path, now: float | None = None) -> Path:
    """Save an uploaded pack under root, in a folder named after its content, and return its path.

    The same bytes always give the same path, and are written only once. Upload folders older than
    KEEP_UPLOADS_SECONDS are deleted first.
    """
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    now = time.time() if now is None else now
    digest = hashlib.sha256(data).hexdigest()[:16]
    folder = root / f"{UPLOAD_FOLDER_PREFIX}{digest}"
    for old in root.glob(f"{UPLOAD_FOLDER_PREFIX}*"):
        if old != folder and old.is_dir() and now - old.stat().st_mtime > KEEP_UPLOADS_SECONDS:
            shutil.rmtree(old, ignore_errors=True)
    # Only the file's own name is kept, so a crafted name cannot point outside the folder.
    target = folder / (Path(file_name).name or "pack.zip")
    if folder.is_dir():
        os.utime(folder)  # Still in use, so the clean-up above keeps it.
    if not target.exists():
        folder.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_bytes(data)
        temporary.replace(target)
    return target


def new_run_dir(root: str | Path, mode: str) -> Path:
    """A run folder that two runs started in the same second cannot share."""
    return Path(root) / f"{mode}_{time.strftime('%Y%m%d_%H%M%S')}_{secrets.token_hex(3)}"
