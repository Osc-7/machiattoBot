"""In-process Automation gateway for channel -> core dispatch."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from schedule_agent.core.interfaces import (
    AgentHooks,
    AgentRunInput,
    AgentRunResult,
    CoreSession,
    ExpireSessionCommand,
    InjectMessageCommand,
    RunTurnCommand,
)

logger = logging.getLogger(__name__)


@dataclass
class SessionCutPolicy:
    idle_timeout_minutes: int = 30
    daily_cutoff_hour: int = 4


class AutomationCoreGateway:
    """
    进程内 Automation 网关。

    将 CLI / 其他 channel 的输入先转成 Automation Command，再下发到 CoreSession。
    """

    def __init__(
        self,
        core_session: CoreSession,
        *,
        session_id: str = "cli:default",
        policy: Optional[SessionCutPolicy] = None,
    ):
        self._core = core_session
        self._session_id = session_id
        self._policy = policy or SessionCutPolicy()
        self._last_activity = datetime.now()

    @property
    def config(self):
        # 兼容 interactive.py 现有读取方式
        return getattr(self._core, "config", None)

    @property
    def raw_core_session(self) -> CoreSession:
        return self._core

    async def run_turn(
        self,
        agent_input: AgentRunInput,
        hooks: AgentHooks | None = None,
    ) -> AgentRunResult:
        command = RunTurnCommand(session_id=self._session_id, input=agent_input)
        result = await self._dispatch_run_turn(command, hooks=hooks)
        self.mark_activity()
        return result

    async def inject_message(
        self,
        command: InjectMessageCommand,
        hooks: AgentHooks | None = None,
    ) -> AgentRunResult:
        result = await self._dispatch_run_turn(
            RunTurnCommand(session_id=command.session_id, input=command.input, metadata=command.metadata),
            hooks=hooks,
        )
        self.mark_activity()
        return result

    def mark_activity(self) -> None:
        self._last_activity = datetime.now()

    def should_expire_session(self) -> bool:
        now = datetime.now()
        idle_seconds = (now - self._last_activity).total_seconds()
        if idle_seconds >= self._policy.idle_timeout_minutes * 60:
            return True
        if self._last_activity.date() < now.date() and now.hour >= self._policy.daily_cutoff_hour:
            return True
        if self._last_activity.date() == now.date() and self._last_activity.hour < self._policy.daily_cutoff_hour <= now.hour:
            return True
        return False

    async def expire_session(self, reason: str = "session_expire") -> None:
        command = ExpireSessionCommand(session_id=self._session_id, reason=reason)
        await self._dispatch_expire(command)
        self.mark_activity()

    async def expire_session_if_needed(self, reason: str = "session_expire") -> bool:
        if not self.should_expire_session():
            return False
        await self.expire_session(reason=reason)
        return True

    async def finalize_session(self):
        return await self._core.finalize_session()

    def reset_session(self) -> None:
        self._core.reset_session()
        self.mark_activity()

    def clear_context(self) -> None:
        clear_fn = getattr(self._core, "clear_context", None)
        if callable(clear_fn):
            clear_fn()

    def get_token_usage(self) -> dict:
        fn = getattr(self._core, "get_token_usage", None)
        if callable(fn):
            return fn()
        return {}

    def get_turn_count(self) -> int:
        state = self._core.get_session_state()
        return state.turn_count

    async def close(self) -> None:
        await self._core.close()

    async def _dispatch_run_turn(
        self,
        command: RunTurnCommand,
        hooks: AgentHooks | None = None,
    ) -> AgentRunResult:
        merged_metadata = dict(command.input.metadata)
        merged_metadata.update(command.metadata)
        merged_metadata.setdefault("session_id", command.session_id)
        agent_input = AgentRunInput(text=command.input.text, metadata=merged_metadata)
        return await self._core.run_turn(agent_input, hooks=hooks)

    async def _dispatch_expire(self, command: ExpireSessionCommand) -> None:
        try:
            await self._core.finalize_session()
        except Exception as exc:
            logger.warning(
                "finalize_session failed during session expire (session_id=%s, reason=%s): %s",
                command.session_id,
                command.reason,
                exc,
            )
        finally:
            self._core.reset_session()
