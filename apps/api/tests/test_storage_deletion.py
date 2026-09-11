"""Deleting a stored object — the capability that did not exist (audit 03, B14).

`Storage` had no `delete` at all, so nothing had ever removed a scan image:
every photograph of every child's handwriting the product has processed was
still in object storage, and erasing a pupil cascaded the database rows and
left the pictures behind.
"""

from __future__ import annotations

import pytest

from alppy.storage import LocalStorage, StorageError


def test_deleting_reports_whether_there_was_anything_there(tmp_path) -> None:
    """A purge that cannot tell "removed 400" from "removed nothing" cannot be
    trusted to report what it did."""
    storage = LocalStorage(tmp_path)
    storage.put_bytes("scans/a/b/page.png", b"bytes", "image/png")

    assert storage.delete("scans/a/b/page.png") is True
    assert storage.exists("scans/a/b/page.png") is False
    # Idempotent: already gone is the outcome the caller wanted.
    assert storage.delete("scans/a/b/page.png") is False


def test_deletion_cannot_escape_the_storage_root(tmp_path) -> None:
    """The traversal guard applies to deletion exactly as it does to reads.

    This is the one method where following a `../../` key would be
    unrecoverable, so it goes through `_path` like everything else rather than
    taking a shortcut.
    """
    storage = LocalStorage(tmp_path / "root")
    outside = tmp_path / "precious.txt"
    outside.write_text("not ours", encoding="utf-8")

    with pytest.raises(StorageError):
        storage.delete("../precious.txt")
    assert outside.exists(), "a key escaping the root deleted a file outside it"
