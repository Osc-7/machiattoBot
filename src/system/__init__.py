"""
System 层 — 调度、会话管理、内核执行。

包含：
- automation：会话管理、IPC、任务队列、CoreGateway
- kernel：AgentKernel、CorePool、KernelScheduler、OutputRouter
"""

from .automation import (
    AgentTask,
    AgentTaskQueue,
    AutomationCoreGateway,
    AutomationIPCClient,
    AutomationIPCServer,
    AutomationRuntime,
    AutomationScheduler,
    IPCServerPolicy,
    SessionCutPolicy,
    SessionManager,
    SessionRegistry,
    default_socket_path,
    get_runtime,
    reset_runtime,
)
from .kernel import (
    AgentKernel,
    CorePool,
    KernelRequest,
    KernelScheduler,
    OutputRouter,
)

__all__ = [
    "AgentKernel",
    "CorePool",
    "KernelRequest",
    "KernelScheduler",
    "OutputRouter",
    "AgentTask",
    "AgentTaskQueue",
    "AutomationCoreGateway",
    "AutomationIPCClient",
    "AutomationIPCServer",
    "AutomationRuntime",
    "AutomationScheduler",
    "IPCServerPolicy",
    "SessionCutPolicy",
    "SessionManager",
    "SessionRegistry",
    "default_socket_path",
    "get_runtime",
    "reset_runtime",
]
