"""Agent Core 抽象协议。"""

from __future__ import annotations

from typing import Protocol

from agent_core.memory import SessionSummary

from .models import AgentHooks, AgentRunInput, AgentRunResult, AgentSessionState


class CoreSession(Protocol):
    """Core 会话稳定接口。"""

    async def run_turn(
        self,
        agent_input: AgentRunInput,
        hooks: AgentHooks | None = None,
    ) -> AgentRunResult:
        ...

    async def finalize_session(self) -> SessionSummary | None:
        ...

    def reset_session(self) -> None:
        ...

    async def close(self) -> None:
        ...

    def get_session_state(self) -> AgentSessionState:
        ...
