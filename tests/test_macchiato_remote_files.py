"""Remote worker file runtime path handling tests."""

from __future__ import annotations

from macchiato_remote.runtime.files import (
    read_workspace_blob,
    read_workspace_text,
    write_workspace_text,
)


def test_blob_size_helpers_roundtrip():
    from macchiato_remote.protocol import (
        REMOTE_BLOB_MAX_BYTES,
        encode_file_too_large,
        format_byte_size,
        parse_file_too_large,
    )

    assert format_byte_size(REMOTE_BLOB_MAX_BYTES) == "100MB"
    from macchiato_remote.protocol import REMOTE_BLOB_STREAM_MAX_BYTES

    assert REMOTE_BLOB_STREAM_MAX_BYTES >= 1024 * 1024 * 1024
    assert format_byte_size(150 * 1024 * 1024) == "150MB"
    encoded = encode_file_too_large(157286400, REMOTE_BLOB_MAX_BYTES)
    assert parse_file_too_large(encoded) == (157286400, REMOTE_BLOB_MAX_BYTES)
    assert parse_file_too_large("nope") is None


def test_absolute_path_read_is_allowed(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("hello-absolute", encoding="utf-8")

    text, truncated, err = read_workspace_text(workspace, str(outside))
    assert err is None
    assert truncated is False
    assert text == "hello-absolute"


def test_absolute_path_write_is_allowed(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside-write.txt"

    written, err = write_workspace_text(workspace, str(outside), "payload")
    assert err is None
    assert written > 0
    assert outside.read_text(encoding="utf-8") == "payload"


def test_read_workspace_blob_supports_absolute_path(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"\x89PNG\r\n\x1a\n")

    b64, name, mime, size, truncated, err = read_workspace_blob(
        workspace, str(outside), max_bytes=1024
    )
    assert err is None
    assert name == "outside.bin"
    assert mime == "application/octet-stream"
    assert size == 8
    assert truncated is False
    assert b64 == "iVBORw0KGgo="


def test_read_workspace_blob_caps_oversize_without_loading_all(tmp_path, monkeypatch):
    """超限文件不读内容，返回 FILE_TOO_LARGE，避免撑爆 WS。"""
    import macchiato_remote.protocol as proto

    monkeypatch.setattr(proto, "REMOTE_BLOB_MAX_BYTES", 64)

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    big = workspace / "big.bin"
    big.write_bytes(b"A" * 100 + b"B" * 50)

    b64, name, mime, size, truncated, err = read_workspace_blob(
        workspace, "big.bin", max_bytes=100
    )
    assert b64 == ""
    assert truncated is True
    assert size == 150
    assert err == "FILE_TOO_LARGE:150:64"

    b64, name, mime, size, truncated, err = read_workspace_blob(
        workspace, "big.bin", max_bytes=32
    )
    assert b64 == ""
    assert truncated is True
    assert size == 150
    assert err == "FILE_TOO_LARGE:150:32"

    small = workspace / "small.bin"
    small.write_bytes(b"ok")
    b64, name, mime, size, truncated, err = read_workspace_blob(
        workspace, "small.bin", max_bytes=32
    )
    assert err is None
    assert truncated is False
    assert size == 2
    assert b64 != ""


def test_write_workspace_blob_relative_inbox(tmp_path):
    import base64

    from macchiato_remote.runtime.files import write_workspace_blob

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    payload = b"hello-blob"
    written, err = write_workspace_blob(
        workspace,
        ".macchiato/inbox/hello.bin",
        base64.b64encode(payload).decode("ascii"),
    )
    assert err is None
    assert written == len(payload)
    assert (workspace / ".macchiato" / "inbox" / "hello.bin").read_bytes() == payload
