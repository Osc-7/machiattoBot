"""Protocol v5 blob stream: frame codec, worker/daemon routing, fallback, e2e."""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from agent_core.remote.worker_registry import (
    RemoteWorkerConnection,
    RemoteWorkerRegistry,
    _PullSession,
)
from macchiato_remote.client import RemoteWorkerClient, worker_hello_payload
from macchiato_remote.protocol import (
    REMOTE_BLOB_MAX_BYTES,
    REMOTE_BLOB_STREAM_MAX_BYTES,
    REMOTE_PROTOCOL_VERSION,
    RemoteBlobPullRequest,
    encode_file_too_large,
    looks_like_blob_chunk,
    normalize_blob_request_id,
    pack_blob_chunk,
    unpack_blob_chunk,
)


def test_pack_unpack_roundtrip_and_seq_range():
    rid = "ab" * 16
    frame = pack_blob_chunk(rid, 7, b"payload")
    got_rid, seq, payload = unpack_blob_chunk(frame)
    assert got_rid == rid
    assert seq == 7
    assert payload == b"payload"
    with pytest.raises(ValueError, match="BLOB_FRAME_TOO_SHORT"):
        unpack_blob_chunk(b"short")
    with pytest.raises(ValueError, match="BLOB_SEQ_OUT_OF_RANGE"):
        pack_blob_chunk(rid, -1, b"x")


def test_normalize_pads_and_looks_like_blob_chunk():
    padded = normalize_blob_request_id("abc")
    assert len(padded) == 32
    assert padded.startswith("abc")
    assert padded.endswith("0")
    frame = pack_blob_chunk("abc", 0, b"xy")
    assert looks_like_blob_chunk(frame)
    assert not looks_like_blob_chunk(b'{"type":"blob_end"}')
    assert not looks_like_blob_chunk(b"x" * 10)


def test_worker_hello_advertises_v5_blob_stream():
    payload = worker_hello_payload()
    assert payload["protocol_version"] == REMOTE_PROTOCOL_VERSION == 5
    assert "blob_stream" in payload["capabilities"]
    assert REMOTE_BLOB_STREAM_MAX_BYTES >= 1024 * 1024 * 1024


def _worker_with_workspace(workspace: Path) -> RemoteWorkerClient:
    worker = RemoteWorkerClient(
        server="http://127.0.0.1:9380",
        login="lab",
        token="tok",
    )
    worker._sessions["sid"] = SimpleNamespace(root=workspace)  # type: ignore[assignment]
    return worker


@pytest.mark.asyncio
async def test_worker_blob_pull_ok_and_too_large_skips_data_frames(tmp_path: Path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    payload = b"hello-stream"
    (workspace / "ok.bin").write_bytes(payload)
    (workspace / "big.bin").write_bytes(b"x" * 32)

    worker = _worker_with_workspace(workspace)
    sent_json: List[Dict[str, Any]] = []
    sent_bytes: List[bytes] = []

    async def send_json(obj: Dict[str, Any]) -> None:
        sent_json.append(obj)

    async def send_bytes(data: bytes) -> None:
        sent_bytes.append(data)

    worker._send_json = send_json
    worker._send_bytes = send_bytes

    await worker._blob_pull(
        RemoteBlobPullRequest(
            request_id="a" * 32,
            session_id="sid",
            path="ok.bin",
            max_bytes=1024,
        )
    )
    types = [m["type"] for m in sent_json]
    assert types == ["blob_begin", "blob_end"]
    assert sent_json[0]["result"]["size"] == len(payload)
    assert sent_json[-1]["result"]["sha256"] == hashlib.sha256(payload).hexdigest()
    assert sent_json[-1]["result"].get("error") in (None, "")
    assert len(sent_bytes) >= 1
    _, seq, chunk = unpack_blob_chunk(sent_bytes[0])
    assert seq == 0
    assert chunk == payload

    sent_json.clear()
    sent_bytes.clear()
    await worker._blob_pull(
        RemoteBlobPullRequest(
            request_id="b" * 32,
            session_id="sid",
            path="big.bin",
            max_bytes=8,
        )
    )
    assert sent_bytes == []
    assert [m["type"] for m in sent_json] == ["blob_end"]
    err = sent_json[0]["result"]["error"]
    assert err == encode_file_too_large(32, 8)


@pytest.mark.asyncio
async def test_worker_blob_pull_file_vanishes_mid_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr("macchiato_remote.client.REMOTE_BLOB_CHUNK_BYTES", 4)
    workspace = tmp_path / "ws"
    workspace.mkdir()
    src = workspace / "x.bin"
    src.write_bytes(b"abcdefghij")
    worker = _worker_with_workspace(workspace)
    sent_json: List[Dict[str, Any]] = []
    sent_bytes: List[bytes] = []

    async def send_json(obj: Dict[str, Any]) -> None:
        sent_json.append(obj)

    async def send_bytes(data: bytes) -> None:
        sent_bytes.append(data)

    worker._send_json = send_json
    worker._send_bytes = send_bytes

    orig_open = Path.open
    reads = {"n": 0}

    def wrapping_open(self, *args, **kwargs):
        handle = orig_open(self, *args, **kwargs)
        orig_read = handle.read

        def read(size=-1):
            reads["n"] += 1
            if reads["n"] > 1:
                raise OSError("file vanished")
            return orig_read(size)

        handle.read = read  # type: ignore[method-assign]
        return handle

    monkeypatch.setattr(Path, "open", wrapping_open)

    await worker._blob_pull(
        RemoteBlobPullRequest(
            request_id="c" * 32,
            session_id="sid",
            path="x.bin",
            max_bytes=1024,
        )
    )
    assert any(m["type"] == "blob_begin" for m in sent_json)
    end = next(m for m in sent_json if m["type"] == "blob_end")
    assert end["result"]["error"]
    assert "vanished" in str(end["result"]["error"])
    assert len(sent_bytes) == 1


@pytest.mark.asyncio
async def test_daemon_routes_interleaved_json_and_concurrent_streams(tmp_path: Path):
    async def noop(_obj: Dict[str, Any]) -> None:
        return None

    conn = RemoteWorkerConnection(login="lab", send_json=noop)
    dest_a = tmp_path / "a.bin"
    dest_b = tmp_path / "b.bin"
    rid_a = "a" * 32
    rid_b = "b" * 32
    sa = _PullSession(request_id=rid_a, dest_path=dest_a)
    sb = _PullSession(request_id=rid_b, dest_path=dest_b)
    conn.stream_sessions[rid_a] = sa
    conn.stream_sessions[rid_b] = sb
    conn.handle_message(
        {
            "type": "blob_begin",
            "result": {
                "request_id": rid_a,
                "size": 3,
                "file_name": "a.bin",
                "mime_type": "application/octet-stream",
            },
        }
    )
    conn.handle_message(
        {
            "type": "blob_begin",
            "result": {
                "request_id": rid_b,
                "size": 3,
                "file_name": "b.bin",
                "mime_type": "application/octet-stream",
            },
        }
    )

    loop = __import__("asyncio").get_running_loop()
    fut = loop.create_future()
    conn.pending["exec1"] = fut

    conn.handle_binary(pack_blob_chunk(rid_a, 0, b"aaa"))
    conn.handle_message(
        {"type": "exec_result", "result": {"request_id": "exec1", "exit_code": 0}}
    )
    conn.handle_binary(pack_blob_chunk(rid_b, 0, b"bbb"))
    assert fut.result()["exit_code"] == 0

    ha = hashlib.sha256(b"aaa").hexdigest()
    hb = hashlib.sha256(b"bbb").hexdigest()
    conn.handle_message(
        {
            "type": "blob_end",
            "result": {
                "request_id": rid_a,
                "sha256": ha,
                "total_bytes": 3,
                "file_name": "a.bin",
            },
        }
    )
    conn.handle_message(
        {
            "type": "blob_end",
            "result": {
                "request_id": rid_b,
                "sha256": hb,
                "total_bytes": 3,
                "file_name": "b.bin",
            },
        }
    )
    out_a = await sa.done
    out_b = await sb.done
    assert out_a.error is None and dest_a.read_bytes() == b"aaa"
    assert out_b.error is None and dest_b.read_bytes() == b"bbb"


@pytest.mark.asyncio
async def test_pull_session_seq_gap_and_sha256_mismatch(tmp_path: Path):
    dest = tmp_path / "x.bin"
    rid = "d" * 32
    session = _PullSession(request_id=rid, dest_path=dest)
    session.on_begin(
        {"size": 2, "file_name": "x.bin", "mime_type": "application/octet-stream"}
    )
    session.on_chunk(1, b"xx")
    out = await session.done
    assert out.error is not None
    assert "BLOB_SEQ_GAP" in out.error

    dest2 = tmp_path / "y.bin"
    s2 = _PullSession(request_id="e" * 32, dest_path=dest2)
    s2.on_begin(
        {"size": 2, "file_name": "y.bin", "mime_type": "application/octet-stream"}
    )
    s2.on_chunk(0, b"yy")
    s2.on_end(
        {
            "sha256": "0" * 64,
            "total_bytes": 2,
            "file_name": "y.bin",
        }
    )
    out2 = await s2.done
    assert out2.error is not None
    assert "BLOB_SHA256_MISMATCH" in out2.error


@pytest.mark.asyncio
async def test_blob_pull_falls_back_to_base64_without_capability(tmp_path: Path):
    raw = b"hello-base64"
    dest = tmp_path / "out.bin"
    calls: List[str] = []

    async def send_json(msg: Dict[str, Any]) -> None:
        calls.append(str(msg.get("type") or ""))

    conn = RemoteWorkerConnection(
        login="lab",
        send_json=send_json,
        hello_meta={
            "protocol_version": 4,
            "capabilities": ["file_blob_read", "file_blob_write"],
        },
    )

    async def fake_request(message_type, payload, timeout_seconds=180.0):
        calls.append(message_type)
        assert message_type == "file_blob_read"
        assert int(payload["max_bytes"]) <= REMOTE_BLOB_MAX_BYTES
        return {
            "request_id": payload["request_id"],
            "path": payload["path"],
            "content_base64": base64.b64encode(raw).decode("ascii"),
            "file_name": "a.bin",
            "mime_type": "application/octet-stream",
            "bytes_read": len(raw),
            "truncated": False,
            "error": None,
        }

    conn.request = fake_request  # type: ignore[method-assign]
    registry = RemoteWorkerRegistry()
    await registry.register(conn)
    assert registry.worker_supports_blob_stream("lab") is False
    outcome = await registry.blob_pull_to_path(
        login="lab", session_id="s", path="a.bin", dest_path=dest
    )
    assert outcome.error is None
    assert dest.read_bytes() == raw
    assert "file_blob_read" in calls
    assert "blob_pull" not in calls


@pytest.mark.asyncio
async def test_blob_push_falls_back_to_base64_without_capability(tmp_path: Path):
    src = tmp_path / "upload.bin"
    src.write_bytes(b"inbox-bytes")
    calls: List[str] = []

    async def send_json(_msg: Dict[str, Any]) -> None:
        return None

    conn = RemoteWorkerConnection(
        login="lab",
        send_json=send_json,
        hello_meta={
            "protocol_version": 4,
            "capabilities": ["file_blob_write"],
        },
    )

    async def fake_request(message_type, payload, timeout_seconds=180.0):
        calls.append(message_type)
        assert message_type == "file_blob_write"
        decoded = base64.b64decode(payload["content_base64"])
        assert decoded == b"inbox-bytes"
        return {
            "request_id": payload["request_id"],
            "path": payload["path"],
            "bytes_written": len(decoded),
            "error": None,
        }

    conn.request = fake_request  # type: ignore[method-assign]
    registry = RemoteWorkerRegistry()
    await registry.register(conn)
    outcome = await registry.blob_push_from_path(
        login="lab",
        session_id="s",
        src_path=src,
        dest_path=".macchiato/inbox/upload.bin",
    )
    assert outcome.error is None
    assert outcome.bytes_written == len(b"inbox-bytes")
    assert calls == ["file_blob_write"]


@pytest.mark.asyncio
async def test_e2e_loopback_pull_and_push_multiple_chunks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    chunk = 8
    monkeypatch.setattr("macchiato_remote.client.REMOTE_BLOB_CHUNK_BYTES", chunk)
    monkeypatch.setattr(
        "agent_core.remote.worker_registry.REMOTE_BLOB_CHUNK_BYTES", chunk
    )

    workspace = tmp_path / "ws"
    workspace.mkdir()
    payload = bytes(range(25))  # 4 chunks with 8-byte size
    (workspace / "out.bin").write_bytes(payload)

    worker = _worker_with_workspace(workspace)
    registry = RemoteWorkerRegistry()
    pull_frames: List[bytes] = []
    push_frames: List[bytes] = []

    async def daemon_send_json(obj: Dict[str, Any]) -> None:
        await worker._dispatch_incoming(json.dumps(obj, ensure_ascii=False))

    async def daemon_send_bytes(data: bytes) -> None:
        push_frames.append(data)
        await worker._dispatch_incoming(data)

    conn = RemoteWorkerConnection(
        login="lab",
        send_json=daemon_send_json,
        send_bytes=daemon_send_bytes,
        hello_meta={"protocol_version": 5, "capabilities": ["blob_stream"]},
    )

    async def worker_send_json(obj: Dict[str, Any]) -> None:
        conn.handle_message(obj)

    async def worker_send_bytes(data: bytes) -> None:
        pull_frames.append(data)
        conn.handle_binary(data)

    worker._send_json = worker_send_json
    worker._send_bytes = worker_send_bytes
    await registry.register(conn)

    dest = tmp_path / "pulled.bin"
    outcome = await registry.blob_pull_to_path(
        login="lab",
        session_id="sid",
        path="out.bin",
        dest_path=dest,
    )
    assert outcome.error is None, outcome.error
    assert dest.read_bytes() == payload
    assert len(pull_frames) >= 3

    local = tmp_path / "upload.bin"
    local.write_bytes(payload)
    push = await registry.blob_push_from_path(
        login="lab",
        session_id="sid",
        src_path=local,
        dest_path=".macchiato/inbox/upload.bin",
    )
    assert push.error is None, push.error
    written = workspace / ".macchiato" / "inbox" / "upload.bin"
    assert written.read_bytes() == payload
    assert len(push_frames) >= 3
    assert registry.worker_supports_blob_stream("lab") is True
