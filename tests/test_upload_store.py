from __future__ import annotations

import pytest

from storage.uploads import UploadStore


def test_upload_source_is_retrievable_only_by_owner_session(tmp_path):
    store = UploadStore(tmp_path)
    source = store.save("session_a", "sales.csv", b"date,sales\n", "request-1")

    selection = store.resolve("session_a", source.source_id)
    assert selection.kind == "csv"
    assert selection.path.read_bytes() == b"date,sales\n"
    with pytest.raises(PermissionError):
        store.resolve("session_b", source.source_id)
    with pytest.raises((PermissionError, ValueError)):
        store.resolve("session_a", "../../outside")


def test_upload_source_enforces_size_suffix_and_nonempty_content(tmp_path):
    store = UploadStore(tmp_path, max_bytes=4)
    with pytest.raises(ValueError, match="size"):
        store.save("session_a", "sales.csv", b"12345", "large")
    with pytest.raises(ValueError, match="extension"):
        store.save("session_a", "sales.exe", b"1", "wrong")
    with pytest.raises(ValueError, match="empty"):
        store.save("session_a", "sales.csv", b"", "empty")


def test_same_upload_key_is_idempotent(tmp_path):
    store = UploadStore(tmp_path)
    first = store.save("session_a", "sales.csv", b"x", "same-key")
    second = store.save("session_a", "different.csv", b"y", "same-key")

    assert first == second
    assert store.resolve("session_a", first.source_id).path.read_bytes() == b"x"
