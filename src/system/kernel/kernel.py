"""
AgentKernel — 纯 IO 调度器（工具执行 + 生命周期管理）。

类比操作系统内核的 syscall 处理器：
- AgentCore 持有 LLMClient，自主完成多轮 LLM 推理（类比 CPU 自执行）
- 只有 ToolCallAction（IO 中断）和 ReturnAction（进程退出）才陷入 Kernel
- Kernel 不参与 LLM 推理的任何环节，也不做 logging/tracing
  ——这些职责由 AgentCore 内部承担，因为它是调用发起方

设计优势：
1. AgentCore 多轮推理无需 Kernel 上下文切换，自旋效率更高
2. 工具调用仍由 Kernel 统一执行，安全策略集中可控
3. 计费/监控状态在 Core 内积累，由 Kernel 在回收时或定期轮询获取
4. 多 Agent 协作天然等价于工具调用，无需额外设计
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any, Dict, Optional

from agent_core.interfaces import AgentHooks, AgentRunResult
from agent_core.kernel_interface import KernelAction, ReturnAction, ToolCallAction, ToolResultEvent

if TYPE_CHECKING:
    from agent_core.agent.agent import ScheduleAgent
    from agent_core.tools import VersionedToolRegistry

logger = logging.getLogger(__name__)


class AgentKernel:
    """
    Agent 系统内核：纯 IO 调度器。

    只持有 ToolRegistry（工具执行权）。
    通过 async generator 协议驱动 AgentCore 的 run_loop()，
    但仅响应两类系统调用：ToolCallAction 和 ReturnAction。

    LLM 推理、Prompt 组装、logging、tracing 全部由 AgentCore 内部完成。

    用法::

        kernel = AgentKernel(tool_registry)
        result = await kernel.run(agent_core, turn_id=1, hooks=hooks)
    """

    def __init__(
        self,
        tool_registry: "VersionedToolRegistry",
        # 以下参数保留仅为向后兼容，不再使用
        llm_client: Any = None,
        loader: Any = None,
        session_logger: Any = None,
    ) -> None:
        self._tools = tool_registry

    async def run(
        self,
        agent: "ScheduleAgent",
        turn_id: int = 0,
        hooks: Optional[AgentHooks] = None,
    ) -> AgentRunResult:
        """
        驱动 AgentCore 的 run_loop()，只处理两类系统调用。

        AgentCore 在 run_loop() 内部直接调用 LLM，自旋完成多轮推理；
        仅在需要工具执行或准备返回时 yield 到此处。

        执行流程：
        1. 启动 agent.run_loop()，hooks 传入供 AgentCore 内部使用
        2. 循环接收 KernelAction：
           - ToolCallAction → ToolRegistry.execute() → asend(ToolResultEvent)
           - ReturnAction   → 终止，返回 AgentRunResult
        """
        gen = agent.run_loop(turn_id=turn_id, hooks=hooks)

        # 启动 generator（到第一个 yield）
        action: KernelAction = await gen.__anext__()

        while True:
            if isinstance(action, ReturnAction):
                return AgentRunResult(
                    output_text=action.message,
                    attachments=action.attachments,
                )

            elif isinstance(action, ToolCallAction):
                result = await self._tools.execute(
                    action.tool_name,
                    **self._parse_arguments(action.arguments),
                )
                action = await gen.asend(ToolResultEvent(
                    tool_call_id=action.tool_call_id,
                    result=result,
                ))

            else:
                logger.warning("AgentKernel: unknown action type %r, stopping", type(action))
                return AgentRunResult(output_text="", metadata={"error": "unknown_action"})

    @staticmethod
    def _parse_arguments(arguments: Any) -> Dict[str, Any]:
        """将工具参数统一解析为 dict。"""
        if isinstance(arguments, dict):
            return arguments
        if isinstance(arguments, str):
            try:
                parsed = json.loads(arguments)
                return parsed if isinstance(parsed, dict) else {}
            except (json.JSONDecodeError, ValueError):
                return {}
        return {}
