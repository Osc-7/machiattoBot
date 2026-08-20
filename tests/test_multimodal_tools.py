"""
多模态媒体挂载工具与回复附图工具测试。
"""

from pathlib import Path

import pytest

from agent_core.agent.media_helpers import collect_outgoing_attachment
from agent_core.config import CommandToolsConfig, Config, FileToolsConfig, LLMConfig
from agent_core.remote.worker_registry import BlobPullOutcome
from agent_core.remote.workspace_state import (
    activate_remote_workspace,
    clear_remote_workspace_state,
)
from agent_core.tools.base import ToolResult
from system.tools.media_tools import (
    AttachFileToReplyTool,
    AttachImageToReplyTool,
    AttachMediaTool,
)


class _FakeBlobRegistry:
    """Stub registry that materializes a remote blob onto dest_path."""

    def __init__(
        self,
        *,
        payload: bytes = b"ok",
        file_name: str = "file.bin",
        mime_type: str = "application/octet-stream",
        error: str | None = None,
        truncated: bool = False,
        raise_exc: BaseException | None = None,
    ) -> None:
        self.payload = payload
        self.file_name = file_name
        self.mime_type = mime_type
        self.error = error
        self.truncated = truncated
        self.raise_exc = raise_exc
        self.file_read = None

    async def blob_pull_to_path(self, **kwargs):
        if self.raise_exc is not None:
            raise self.raise_exc
        dest = Path(kwargs["dest_path"])
        dest.parent.mkdir(parents=True, exist_ok=True)
        if self.error is None and not self.truncated:
            dest.write_bytes(self.payload)
            dest_path = str(dest)
        else:
            dest_path = None
        return BlobPullOutcome(
            dest_path=dest_path,
            file_name=self.file_name,
            mime_type=self.mime_type,
            bytes_read=len(self.payload),
            error=self.error,
            truncated=self.truncated,
        )


def _workspace_config(tmp_path):
    return Config(
        llm=LLMConfig(api_key="k", model="m"),
        file_tools=FileToolsConfig(base_dir=str(tmp_path)),
        command_tools=CommandToolsConfig(
            base_dir=str(tmp_path),
            workspace_base_dir=str(tmp_path / "workspace_parent"),
            workspace_isolation_enabled=True,
        ),
    )


def test_collect_outgoing_attachment_supports_inline_base64_file():
    result = ToolResult(
        success=True,
        data=None,
        message="ok",
        metadata={
            "outgoing_attachment": {
                "type": "file",
                "content_base64": "b2s=",
                "file_name": "report.txt",
                "mime_type": "text/plain",
            }
        },
    )
    attachments = []

    collect_outgoing_attachment(result, attachments)

    assert attachments == [
        {
            "type": "file",
            "content_base64": "b2s=",
            "file_name": "report.txt",
            "mime_type": "text/plain",
        }
    ]


class TestAttachMediaTool:
    @pytest.mark.asyncio
    async def test_execute_requires_path_or_paths(self):
        tool = AttachMediaTool()
        result = await tool.execute()
        assert result.success is False
        assert result.error == "MISSING_MEDIA_PATH"

    @pytest.mark.asyncio
    async def test_execute_with_single_path(self, tmp_path):
        img = tmp_path / "page_1.png"
        img.write_bytes(
            bytes.fromhex(
                "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
                "0000000a49444154789c63000100000500010d0a2db40000000049454e44ae426082"
            )
        )
        tool = AttachMediaTool(config=_workspace_config(tmp_path))
        result = await tool.execute(path=str(img))
        assert result.success is True
        assert result.metadata.get("embed_in_next_call") is True
        assert result.metadata.get("media_items")
        assert result.metadata["media_items"][0]["type"] == "media_ref"
        assert result.data["paths"] == [str(img)]

    @pytest.mark.asyncio
    async def test_execute_with_paths_list_merges_and_deduplicates(self, tmp_path):
        a = tmp_path / "a.png"
        b = tmp_path / "b.png"
        payload = bytes.fromhex(
            "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
            "0000000a49444154789c63000100000500010d0a2db40000000049454e44ae426082"
        )
        a.write_bytes(payload)
        b.write_bytes(payload)
        tool = AttachMediaTool(config=_workspace_config(tmp_path))
        result = await tool.execute(path=str(a), paths=[str(a), str(b)])
        assert result.success is True
        assert result.data["paths"] == [str(a), str(b)]
        assert len(result.metadata["media_items"]) == 2

    @pytest.mark.asyncio
    async def test_execute_remote_workspace_pulls_blob_to_local_media_ref(
        self, tmp_path, monkeypatch
    ):
        """远程工作区下 attach_media 应从 worker 拉取图片并落成本地 media_ref。"""
        cfg = _workspace_config(tmp_path)
        tool = AttachMediaTool(config=cfg)
        png_bytes = bytes.fromhex(
            "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
            "0000000a49444154789c63000100000500010d0a2db40000000049454e44ae426082"
        )
        clear_remote_workspace_state()
        try:
            activate_remote_workspace(
                session_id="feishu:u1",
                login="local-dev",
                requested_path="~/proj",
                resolved_path=str(tmp_path / "remote-proj"),
            )
            import agent_core.remote.worker_registry as registry_mod

            monkeypatch.setattr(
                registry_mod,
                "get_remote_worker_registry",
                lambda: _FakeBlobRegistry(
                    payload=png_bytes,
                    file_name="shot.png",
                    mime_type="image/png",
                ),
            )
            result = await tool.execute(
                path="outputs/shot.png",
                __execution_context__={
                    "source": "feishu",
                    "user_id": "u1",
                    "session_id": "feishu:u1",
                },
            )
        finally:
            clear_remote_workspace_state()

        assert result.success is True, result.message
        items = result.metadata.get("media_items") or []
        assert len(items) == 1
        assert items[0]["type"] == "media_ref"
        assert items[0]["media_type"] == "image"
        local_path = Path(items[0]["path"])
        assert local_path.is_file()
        assert local_path.read_bytes() == png_bytes

    @pytest.mark.asyncio
    async def test_execute_accepts_local_video_path(self, tmp_path):
        mp4 = tmp_path / "clip.mp4"
        mp4.write_bytes(b"\x00\x00\x00\x18ftypmp42")
        tool = AttachMediaTool(config=_workspace_config(tmp_path))
        result = await tool.execute(path=str(mp4))
        assert result.success is True, result.message
        items = result.metadata.get("media_items") or []
        assert len(items) == 1
        assert items[0]["media_type"] == "video"
        assert "视频需 vendor_files_api" in result.message or "含视频" in result.message


class TestAttachImageToReplyTool:
    @pytest.mark.asyncio
    async def test_execute_requires_image_path_or_image_url(self):
        tool = AttachImageToReplyTool()
        result = await tool.execute()
        assert result.success is False
        assert result.error == "INVALID_INPUT"
        result_both = await tool.execute(
            image_path="/tmp/x.png", image_url="https://example.com/x.png"
        )
        assert result_both.success is False

    @pytest.mark.asyncio
    async def test_execute_with_nonexistent_path_fails(self):
        tool = AttachImageToReplyTool()
        result = await tool.execute(image_path="/nonexistent/image_xyz_12345.png")
        assert result.success is False
        assert result.error == "FILE_NOT_FOUND"

    @pytest.mark.asyncio
    async def test_execute_with_valid_path_returns_outgoing_attachment(self, tmp_path):
        (tmp_path / "test.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        tool = AttachImageToReplyTool()
        result = await tool.execute(image_path=str(tmp_path / "test.png"))
        assert result.success is True
        assert result.metadata.get("outgoing_attachment") == {
            "type": "image",
            "path": str((tmp_path / "test.png").resolve()),
        }
        assert "path" in result.data and result.data["type"] == "image"

    @pytest.mark.asyncio
    async def test_execute_with_workspace_relative_path(self, tmp_path):
        cfg = _workspace_config(tmp_path)
        img = tmp_path / "workspace_parent" / "feishu" / "u1" / "pic.png"
        img.parent.mkdir(parents=True)
        img.write_bytes(b"\x89PNG\r\n\x1a\n")
        tool = AttachImageToReplyTool(config=cfg)

        result = await tool.execute(
            image_path="pic.png",
            __execution_context__={"source": "feishu", "user_id": "u1"},
        )

        assert result.success is True
        assert result.data["path"] == str(img.resolve())

    @pytest.mark.asyncio
    async def test_execute_with_url_returns_outgoing_attachment(self):
        tool = AttachImageToReplyTool()
        result = await tool.execute(image_url="https://example.com/diagram.png")
        assert result.success is True
        assert result.metadata.get("outgoing_attachment") == {
            "type": "image",
            "url": "https://example.com/diagram.png",
        }

    @pytest.mark.asyncio
    async def test_execute_with_invalid_url_fails(self):
        tool = AttachImageToReplyTool()
        result = await tool.execute(image_url="not-a-url")
        assert result.success is False
        assert result.error == "INVALID_URL"

    @pytest.mark.asyncio
    async def test_execute_with_remote_workspace_image_path_succeeds(
        self, tmp_path, monkeypatch
    ):
        cfg = _workspace_config(tmp_path)
        tool = AttachImageToReplyTool(config=cfg)
        clear_remote_workspace_state()
        try:
            activate_remote_workspace(
                session_id="feishu:u1",
                login="local-dev",
                requested_path="~/proj",
                resolved_path=str(tmp_path / "remote-proj"),
            )
            import agent_core.remote.worker_registry as registry_mod

            monkeypatch.setattr(
                registry_mod,
                "get_remote_worker_registry",
                lambda: _FakeBlobRegistry(
                    payload=b"\x89PNG\r\n\x1a\n",
                    file_name="pic.png",
                    mime_type="image/png",
                ),
            )
            result = await tool.execute(
                image_path="pic.png",
                __execution_context__={
                    "source": "feishu",
                    "user_id": "u1",
                    "session_id": "feishu:u1",
                },
            )
        finally:
            clear_remote_workspace_state()

        assert result.success is True
        att = result.metadata.get("outgoing_attachment") or {}
        assert att["type"] == "image"
        assert att["content_type"] == "image/png"
        assert att["file_name"] == "pic.png"
        assert Path(att["path"]).is_file()
        assert Path(att["path"]).read_bytes().startswith(b"\x89PNG")

    @pytest.mark.asyncio
    async def test_execute_with_remote_workspace_image_blob_timeout_returns_remote_error(
        self, tmp_path, monkeypatch
    ):
        cfg = _workspace_config(tmp_path)
        tool = AttachImageToReplyTool(config=cfg)
        clear_remote_workspace_state()
        try:
            activate_remote_workspace(
                session_id="feishu:u1",
                login="local-dev",
                requested_path="~/proj",
                resolved_path=str(tmp_path / "remote-proj"),
            )
            import agent_core.remote.worker_registry as registry_mod

            monkeypatch.setattr(
                registry_mod,
                "get_remote_worker_registry",
                lambda: _FakeBlobRegistry(raise_exc=TimeoutError()),
            )
            result = await tool.execute(
                image_path="pic.png",
                __execution_context__={
                    "source": "feishu",
                    "user_id": "u1",
                    "session_id": "feishu:u1",
                },
            )
        finally:
            clear_remote_workspace_state()

        assert result.success is False
        assert result.error == "REMOTE_ATTACHMENT_READ_FAILED"
        assert "超时" in result.message


class TestAttachFileToReplyTool:
    @pytest.mark.asyncio
    async def test_execute_requires_file_path_or_file_url(self):
        tool = AttachFileToReplyTool()
        result = await tool.execute()
        assert result.success is False
        assert result.error == "INVALID_INPUT"

    @pytest.mark.asyncio
    async def test_execute_with_valid_path_returns_outgoing_attachment(self, tmp_path):
        p = tmp_path / "report.txt"
        p.write_text("ok", encoding="utf-8")
        tool = AttachFileToReplyTool()
        result = await tool.execute(file_path=str(p))
        assert result.success is True
        assert result.metadata.get("outgoing_attachment") == {
            "type": "file",
            "path": str(p.resolve()),
        }

    @pytest.mark.asyncio
    async def test_execute_with_workspace_relative_path(self, tmp_path):
        cfg = _workspace_config(tmp_path)
        p = tmp_path / "workspace_parent" / "feishu" / "u1" / "report.txt"
        p.parent.mkdir(parents=True)
        p.write_text("ok", encoding="utf-8")
        tool = AttachFileToReplyTool(config=cfg)

        result = await tool.execute(
            file_path="report.txt",
            __execution_context__={"source": "feishu", "user_id": "u1"},
        )

        assert result.success is True
        assert result.data["path"] == str(p.resolve())

    @pytest.mark.asyncio
    async def test_execute_with_remote_workspace_path_reads_blob_and_succeeds(
        self, tmp_path, monkeypatch
    ):
        cfg = _workspace_config(tmp_path)
        tool = AttachFileToReplyTool(config=cfg)
        clear_remote_workspace_state()
        try:
            activate_remote_workspace(
                session_id="feishu:u1",
                login="local-dev",
                requested_path="~/proj",
                resolved_path=str(tmp_path / "remote-proj"),
            )
            import agent_core.remote.worker_registry as registry_mod

            monkeypatch.setattr(
                registry_mod,
                "get_remote_worker_registry",
                lambda: _FakeBlobRegistry(
                    payload=b"ok",
                    file_name="report.txt",
                    mime_type="text/plain",
                ),
            )
            result = await tool.execute(
                file_path="report.txt",
                __execution_context__={
                    "source": "feishu",
                    "user_id": "u1",
                    "session_id": "feishu:u1",
                },
            )
        finally:
            clear_remote_workspace_state()

        assert result.success is True
        att = result.metadata.get("outgoing_attachment") or {}
        assert att["type"] == "file"
        assert att["mime_type"] == "text/plain"
        assert att["file_name"] == "report.txt"
        assert Path(att["path"]).read_bytes() == b"ok"

    @pytest.mark.asyncio
    async def test_execute_with_remote_workspace_path_falls_back_to_text_read(
        self, tmp_path, monkeypatch
    ):
        cfg = _workspace_config(tmp_path)
        tool = AttachFileToReplyTool(config=cfg)
        clear_remote_workspace_state()
        try:
            activate_remote_workspace(
                session_id="feishu:u1",
                login="local-dev",
                requested_path="~/proj",
                resolved_path=str(tmp_path / "remote-proj"),
            )
            import agent_core.remote.worker_registry as registry_mod

            fake = _FakeBlobRegistry(raise_exc=TimeoutError())

            class _R:
                error = None
                content = "report content"
                truncated = False

            async def _file_read(**kwargs):
                return _R()

            fake.file_read = _file_read
            monkeypatch.setattr(
                registry_mod, "get_remote_worker_registry", lambda: fake
            )
            result = await tool.execute(
                file_path="report.txt",
                __execution_context__={
                    "source": "feishu",
                    "user_id": "u1",
                    "session_id": "feishu:u1",
                },
            )
        finally:
            clear_remote_workspace_state()

        assert result.success is True
        assert result.metadata.get("outgoing_attachment") == {
            "type": "file",
            "content_base64": "cmVwb3J0IGNvbnRlbnQ=",
            "mime_type": "text/plain; charset=utf-8",
            "file_name": "report.txt",
        }

    @pytest.mark.asyncio
    async def test_execute_remote_truncated_blob_returns_too_large(
        self, tmp_path, monkeypatch
    ):
        cfg = _workspace_config(tmp_path)
        tool = AttachFileToReplyTool(config=cfg)
        clear_remote_workspace_state()
        try:
            activate_remote_workspace(
                session_id="feishu:u1",
                login="local-dev",
                requested_path="~/proj",
                resolved_path=str(tmp_path / "remote-proj"),
            )
            import agent_core.remote.worker_registry as registry_mod

            monkeypatch.setattr(
                registry_mod,
                "get_remote_worker_registry",
                lambda: _FakeBlobRegistry(
                    payload=b"ok",
                    file_name="big.mp4",
                    mime_type="video/mp4",
                    truncated=True,
                ),
            )
            result = await tool.execute(
                file_path="big.mp4",
                __execution_context__={
                    "source": "feishu",
                    "user_id": "u1",
                    "session_id": "feishu:u1",
                },
            )
        finally:
            clear_remote_workspace_state()

        assert result.success is False
        assert result.error == "REMOTE_ATTACHMENT_TOO_LARGE"
        assert "过大" in result.message
        assert "1024MB" in result.message

    @pytest.mark.asyncio
    async def test_execute_remote_file_too_large_code_includes_actual_size(
        self, tmp_path, monkeypatch
    ):
        cfg = _workspace_config(tmp_path)
        tool = AttachFileToReplyTool(config=cfg)
        clear_remote_workspace_state()
        try:
            activate_remote_workspace(
                session_id="feishu:u1",
                login="local-dev",
                requested_path="~/proj",
                resolved_path=str(tmp_path / "remote-proj"),
            )
            import agent_core.remote.worker_registry as registry_mod

            monkeypatch.setattr(
                registry_mod,
                "get_remote_worker_registry",
                lambda: _FakeBlobRegistry(
                    file_name="big.mp4",
                    mime_type="video/mp4",
                    error="FILE_TOO_LARGE:157286400:104857600",
                    truncated=True,
                ),
            )
            result = await tool.execute(
                file_path="big.mp4",
                __execution_context__={
                    "source": "feishu",
                    "user_id": "u1",
                    "session_id": "feishu:u1",
                },
            )
        finally:
            clear_remote_workspace_state()

        assert result.success is False
        assert result.error == "REMOTE_ATTACHMENT_TOO_LARGE"
        assert "过大" in result.message
        assert "150MB" in result.message
        assert "100MB" in result.message

    @pytest.mark.asyncio
    async def test_execute_remote_worker_disconnected_does_not_text_fallback(
        self, tmp_path, monkeypatch
    ):
        """WS 断连后不要再走文本兜底（会二次失败并掩盖根因）。"""
        cfg = _workspace_config(tmp_path)
        tool = AttachFileToReplyTool(config=cfg)
        clear_remote_workspace_state()
        try:
            activate_remote_workspace(
                session_id="feishu:u1",
                login="local-dev",
                requested_path="~/proj",
                resolved_path=str(tmp_path / "remote-proj"),
            )
            import agent_core.remote.worker_registry as registry_mod

            fake = _FakeBlobRegistry(raise_exc=RuntimeError("远程 worker 未连接: sii"))

            async def _file_read(**kwargs):
                raise AssertionError("should not text-fallback after disconnect")

            fake.file_read = _file_read
            monkeypatch.setattr(
                registry_mod, "get_remote_worker_registry", lambda: fake
            )
            result = await tool.execute(
                file_path="vid.mp4",
                __execution_context__={
                    "source": "feishu",
                    "user_id": "u1",
                    "session_id": "feishu:u1",
                },
            )
        finally:
            clear_remote_workspace_state()

        assert result.success is False
        assert result.error == "REMOTE_ATTACHMENT_READ_FAILED"
        assert "未连接" in result.message
        assert "文件过大" in result.message

    @pytest.mark.asyncio
    async def test_execute_with_url_returns_outgoing_attachment(self):
        tool = AttachFileToReplyTool()
        result = await tool.execute(
            file_url="https://example.com/spec.pdf", file_name="spec.pdf"
        )
        assert result.success is True
        assert result.metadata.get("outgoing_attachment") == {
            "type": "file",
            "url": "https://example.com/spec.pdf",
            "file_name": "spec.pdf",
        }
