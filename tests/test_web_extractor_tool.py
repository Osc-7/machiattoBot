"""
网页抓取工具测试
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from schedule_agent.core.tools import WebExtractorTool
from schedule_agent.config import Config, LLMConfig


@pytest.fixture
def mock_config():
    """创建模拟配置"""
    return Config(
        llm=LLMConfig(
            provider="qwen",
            api_key="test-api-key",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            model="qwen3-max-2026-01-23",
            temperature=0.7,
            max_tokens=4096,
        )
    )


class TestWebExtractorTool:
    """测试 WebExtractorTool"""

    def test_tool_initialization(self, mock_config):
        """测试工具初始化"""
        tool = WebExtractorTool(config=mock_config)
        assert tool.name == "extract_web_content"

    def test_get_definition(self, mock_config):
        """测试工具定义"""
        tool = WebExtractorTool(config=mock_config)
        definition = tool.get_definition()
        
        assert definition.name == "extract_web_content"
        assert len(definition.parameters) == 2
        assert definition.parameters[0].name == "url"
        assert definition.parameters[1].name == "query"

    @pytest.mark.asyncio
    async def test_execute_missing_url(self, mock_config):
        """测试缺少 URL 参数"""
        tool = WebExtractorTool(config=mock_config)
        result = await tool.execute()
        
        assert result.success is False
        assert result.error == "MISSING_URL"

    @pytest.mark.asyncio
    async def test_execute_invalid_url(self, mock_config):
        """测试无效 URL"""
        tool = WebExtractorTool(config=mock_config)
        result = await tool.execute(url="invalid-url")
        
        assert result.success is False
        assert result.error == "INVALID_URL"

    @pytest.mark.asyncio
    async def test_execute_success(self, mock_config):
        """测试成功执行网页抓取"""
        async def mock_stream():
            """模拟流式响应"""
            chunk1 = MagicMock()
            chunk1.choices = [MagicMock()]
            chunk1.choices[0].delta = MagicMock()
            chunk1.choices[0].delta.content = "这是网页"
            chunk1.choices[0].delta.tool_calls = None
            chunk1.choices[0].finish_reason = None
            chunk1.usage = None
            yield chunk1

            chunk2 = MagicMock()
            chunk2.choices = [MagicMock()]
            chunk2.choices[0].delta = MagicMock()
            chunk2.choices[0].delta.content = "内容总结"
            chunk2.choices[0].delta.tool_calls = None
            chunk2.choices[0].finish_reason = "stop"
            chunk2.usage = MagicMock()
            chunk2.usage.prompt_tokens = 100
            chunk2.usage.completion_tokens = 50
            chunk2.usage.total_tokens = 150
            yield chunk2

        with patch("schedule_agent.core.llm.client.AsyncOpenAI") as mock_openai:
            mock_client = AsyncMock()
            mock_client.chat.completions.create = AsyncMock(return_value=mock_stream())
            mock_client.close = AsyncMock()
            mock_openai.return_value = mock_client

            tool = WebExtractorTool(config=mock_config)
            tool._llm_client._client = mock_client

            result = await tool.execute(url="https://example.com", query="总结内容")

            assert result.success is True
            assert result.data["url"] == "https://example.com"
            assert "网页" in result.data["content"] and "内容总结" in result.data["content"]
            assert "成功提取网页内容" in result.message

            # 验证使用了流式调用和正确的配置
            call_args = mock_client.chat.completions.create.call_args
            assert call_args.kwargs["stream"] is True
            assert "extra_body" in call_args.kwargs
            extra_body = call_args.kwargs["extra_body"]
            assert extra_body["enable_search"] is True
            assert extra_body["enable_thinking"] is True
            assert "search_options" in extra_body
            assert extra_body["search_options"]["search_strategy"] == "agent_max"

            await tool.close()
