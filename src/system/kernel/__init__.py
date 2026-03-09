"""
System Kernel — 纯 IO 调度器（工具执行 + 生命周期管理）。

类比操作系统内核，负责：
- AgentKernel：执行 ToolCallAction，驱动 AgentCore
- CorePool：进程表，session → AgentCore 的创建/复用/回收
- KernelScheduler + OutputRouter：输入队列 + 乱序完成路由

协议类型（ToolCallAction, ReturnAction, KernelRequest 等）定义在 agent_core.kernel_interface。
"""

from agent_core.kernel_interface import (
    KernelAction,
    KernelEvent,
    KernelRequest,
    ReturnAction,
    ToolCallAction,
    ToolResultEvent,
    InternalLoader,
    LLMPayload,
)
from .core_pool import CorePool
from .kernel import AgentKernel
from .scheduler import KernelScheduler, OutputRouter

__all__ = [
    "KernelAction",
    "KernelEvent",
    "KernelRequest",
    "ReturnAction",
    "ToolCallAction",
    "ToolResultEvent",
    "InternalLoader",
    "LLMPayload",
    "AgentKernel",
    "CorePool",
    "KernelScheduler",
    "OutputRouter",
]
