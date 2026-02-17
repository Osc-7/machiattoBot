"""
LLM 客户端测试
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from schedule_agent.core.llm import LLMClient, LLMResponse, ToolCall
from schedule_agent.config import Config, LLMConfig


@pytest.fixture
def mock_config():
    """创建模拟配置"""
    return Config(
        llm=LLMConfig(
            provider="doubao",
            api_key="test-api-key",
            base_url="https://ark.cn-beijing.volces.com/api/v3",
            model="ep-test-model",
            temperature=0.7,
            max_tokens=4096,
        )
    )


@pytest.fixture
def mock_openai_response():
    """创建模拟 OpenAI 响应"""
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.content = "这是助手的回复"
    response.choices[0].message.tool_calls = None
    response.choices[0].finish_reason = "stop"
    return response


@pytest.fixture
def mock_openai_response_with_tools():
    """创建带工具调用的模拟响应"""
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.content = None

    # 模拟工具调用
    tool_call = MagicMock()
    tool_call.id = "call_123"
    tool_call.function.name = "create_event"
    tool_call.function.arguments = '{"title": "测试事件", "start_time": "2026-02-18 10:00"}'

    response.choices[0].message.tool_calls = [tool_call]
    response.choices[0].finish_reason = "tool_calls"
    return response


class TestToolCall:
    """测试 ToolCall 数据类"""

    def test_tool_call_creation(self):
        """测试工具调用创建"""
        tool_call = ToolCall(
            id="call_123",
            name="create_event",
            arguments={"title": "测试事件"},
        )

        assert tool_call.id == "call_123"
        assert tool_call.name == "create_event"
        assert tool_call.arguments == {"title": "测试事件"}


class TestLLMResponse:
    """测试 LLMResponse 数据类"""

    def test_response_creation(self):
        """测试响应创建"""
        response = LLMResponse(
            content="这是回复",
            tool_calls=[],
            finish_reason="stop",
        )

        assert response.content == "这是回复"
        assert response.tool_calls == []
        assert response.finish_reason == "stop"

    def test_response_with_tool_calls(self):
        """测试带工具调用的响应"""
        tool_call = ToolCall(
            id="call_123",
            name="create_event",
            arguments={"title": "测试"},
        )

        response = LLMResponse(
            content=None,
            tool_calls=[tool_call],
            finish_reason="tool_calls",
        )

        assert response.content is None
        assert len(response.tool_calls) == 1
        assert response.tool_calls[0].name == "create_event"


class TestLLMClient:
    """测试 LLMClient"""

    def test_client_initialization(self, mock_config):
        """测试客户端初始化"""
        client = LLMClient(config=mock_config)

        assert client.model == "ep-test-model"
        assert client.temperature == 0.7
        assert client.max_tokens == 4096

    @pytest.mark.asyncio
    async def test_chat_basic(self, mock_config, mock_openai_response):
        """测试基础对话"""
        with patch("schedule_agent.core.llm.client.AsyncOpenAI") as mock_openai:
            mock_client = AsyncMock()
            mock_client.chat.completions.create = AsyncMock(
                return_value=mock_openai_response
            )
            mock_client.close = AsyncMock()
            mock_openai.return_value = mock_client

            client = LLMClient(config=mock_config)
            client._client = mock_client

            response = await client.chat(
                messages=[{"role": "user", "content": "你好"}],
                system_message="你是一个助手",
            )

            assert response.content == "这是助手的回复"
            assert response.tool_calls == []
            assert response.finish_reason == "stop"

            # 验证调用参数
            call_args = mock_client.chat.completions.create.call_args
            assert call_args.kwargs["model"] == "ep-test-model"
            assert len(call_args.kwargs["messages"]) == 2  # system + user

    @pytest.mark.asyncio
    async def test_chat_with_tools(
        self, mock_config, mock_openai_response_with_tools
    ):
        """测试带工具的对话"""
        with patch("schedule_agent.core.llm.client.AsyncOpenAI") as mock_openai:
            mock_client = AsyncMock()
            mock_client.chat.completions.create = AsyncMock(
                return_value=mock_openai_response_with_tools
            )
            mock_client.close = AsyncMock()
            mock_openai.return_value = mock_client

            client = LLMClient(config=mock_config)
            client._client = mock_client

            tools = [
                {
                    "type": "function",
                    "function": {
                        "name": "create_event",
                        "description": "创建事件",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string"},
                            },
                        },
                    },
                }
            ]

            response = await client.chat_with_tools(
                messages=[{"role": "user", "content": "创建一个会议"}],
                tools=tools,
                system_message="你是一个日程助手",
            )

            assert response.content is None
            assert len(response.tool_calls) == 1
            assert response.tool_calls[0].name == "create_event"
            assert response.tool_calls[0].id == "call_123"

            # 验证调用参数
            call_args = mock_client.chat.completions.create.call_args
            assert "tools" in call_args.kwargs
            assert call_args.kwargs["tool_choice"] == "auto"

    @pytest.mark.asyncio
    async def test_chat_without_tools(self, mock_config, mock_openai_response):
        """测试不带工具的 chat_with_tools"""
        with patch("schedule_agent.core.llm.client.AsyncOpenAI") as mock_openai:
            mock_client = AsyncMock()
            mock_client.chat.completions.create = AsyncMock(
                return_value=mock_openai_response
            )
            mock_client.close = AsyncMock()
            mock_openai.return_value = mock_client

            client = LLMClient(config=mock_config)
            client._client = mock_client

            response = await client.chat_with_tools(
                messages=[{"role": "user", "content": "你好"}],
                tools=None,
            )

            assert response.content == "这是助手的回复"

            # 验证调用参数不包含 tools
            call_args = mock_client.chat.completions.create.call_args
            assert "tools" not in call_args.kwargs

    @pytest.mark.asyncio
    async def test_close(self, mock_config):
        """测试关闭客户端"""
        with patch("schedule_agent.core.llm.client.AsyncOpenAI") as mock_openai:
            mock_client = AsyncMock()
            mock_client.close = AsyncMock()
            mock_openai.return_value = mock_client

            client = LLMClient(config=mock_config)
            await client.close()

            mock_client.close.assert_called_once()


class TestLLMClientIntegration:
    """LLM 客户端集成测试（需要真实 API）"""

    @pytest.mark.skip(reason="需要真实 API Key")
    @pytest.mark.asyncio
    async def test_real_chat(self):
        """测试真实 API 调用（跳过）"""
        # 此测试需要真实的 API Key 和端点
        # 仅在手动测试时启用
        pass
