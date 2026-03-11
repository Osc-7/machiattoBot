"""
Agent Core — 核心执行层。

包含 AgentCore、LLM 客户端、工具系统、上下文管理、记忆系统、内核协议（action/loader）。
"""

from .agent.agent import AgentCore
from .adapters.core_session_adapter import CoreSessionAdapter
from .context import ConversationContext, TimeContext, get_time_context
from .interfaces import (
    AgentHooks,
    AgentRunInput,
    AgentRunResult,
    AgentSessionState,
    CoreEvent,
    CoreSession,
    ExpireSessionCommand,
    InjectMessageCommand,
    RESERVED_METADATA_KEYS,
    RunTurnCommand,
    merge_run_metadata,
)
from .llm import LLMClient, LLMResponse, ToolCall
from .tools import BaseTool, ToolDefinition, ToolParameter, ToolRegistry, ToolResult
from .kernel_interface import (
    KernelAction,
    KernelEvent,
    KernelRequest,
    ReturnAction,
    ToolCallAction,
    ToolResultEvent,
    InternalLoader,
    LLMPayload,
)

__all__ = [
    "AgentCore",
    "CoreSessionAdapter",
    "CoreSession",
    "CoreEvent",
    "AgentHooks",
    "AgentRunInput",
    "AgentRunResult",
    "AgentSessionState",
    "RunTurnCommand",
    "InjectMessageCommand",
    "ExpireSessionCommand",
    "RESERVED_METADATA_KEYS",
    "merge_run_metadata",
    "LLMClient",
    "LLMResponse",
    "ToolCall",
    "ConversationContext",
    "TimeContext",
    "get_time_context",
    "BaseTool",
    "ToolDefinition",
    "ToolParameter",
    "ToolRegistry",
    "ToolResult",
    "KernelAction",
    "KernelEvent",
    "KernelRequest",
    "ReturnAction",
    "ToolCallAction",
    "ToolResultEvent",
    "InternalLoader",
    "LLMPayload",
]
