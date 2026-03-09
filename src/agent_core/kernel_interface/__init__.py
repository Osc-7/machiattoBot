"""
Agent Core 内核协议 — syscall 接口定义与 InternalLoader。

供 ScheduleAgent.run_loop() 使用，供 system.kernel 导入。
"""

from .action import (
    KernelAction,
    KernelEvent,
    KernelRequest,
    ReturnAction,
    ToolCallAction,
    ToolResultEvent,
)
from .loader import InternalLoader, LLMPayload

__all__ = [
    "KernelAction",
    "KernelEvent",
    "KernelRequest",
    "ReturnAction",
    "ToolCallAction",
    "ToolResultEvent",
    "InternalLoader",
    "LLMPayload",
]
