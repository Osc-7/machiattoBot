"""
多模态媒体挂载工具测试。
"""

import pytest

from schedule_agent.core.tools.media_tools import AttachMediaTool


class TestAttachMediaTool:
    @pytest.mark.asyncio
    async def test_execute_requires_path_or_paths(self):
        tool = AttachMediaTool()
        result = await tool.execute()
        assert result.success is False
        assert result.error == "MISSING_MEDIA_PATH"

    @pytest.mark.asyncio
    async def test_execute_with_single_path(self):
        tool = AttachMediaTool()
        result = await tool.execute(path="user_file/page_1.png")
        assert result.success is True
        assert result.metadata.get("embed_in_next_call") is True
        assert "paths" in result.data
        assert result.data["paths"] == ["user_file/page_1.png"]

    @pytest.mark.asyncio
    async def test_execute_with_paths_list_merges_and_deduplicates(self):
        tool = AttachMediaTool()
        result = await tool.execute(
            path="user_file/a.png",
            paths=["user_file/a.png", "user_file/b.png"],
        )
        assert result.success is True
        assert result.data["paths"] == ["user_file/a.png", "user_file/b.png"]
