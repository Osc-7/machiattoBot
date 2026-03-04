"""AutomationCoreGateway tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from schedule_agent.automation import AutomationCoreGateway, SessionCutPolicy
from schedule_agent.core.interfaces import AgentHooks, AgentRunInput, AgentRunResult, InjectMessageCommand


@pytest.mark.asyncio
async def test_gateway_dispatches_run_turn_and_updates_activity():
    core = AsyncMock()
    core.run_turn = AsyncMock(return_value=AgentRunResult(output_text="ok"))
    core.get_session_state = MagicMock(return_value=MagicMock(turn_count=1))
    core.get_token_usage = MagicMock(return_value={"total_tokens": 3})

    gateway = AutomationCoreGateway(core, session_id="cli:default")
    result = await gateway.run_turn(AgentRunInput(text="hello"), hooks=AgentHooks())

    assert result.output_text == "ok"
    core.run_turn.assert_awaited_once()
    call = core.run_turn.await_args
    assert call.args[0].text == "hello"
    assert call.args[0].metadata["session_id"] == "cli:default"


@pytest.mark.asyncio
async def test_gateway_expire_flow_calls_finalize_then_reset():
    core = AsyncMock()
    core.finalize_session = AsyncMock(return_value=None)
    core.reset_session = MagicMock()
    core.run_turn = AsyncMock(return_value=AgentRunResult(output_text="ok"))
    core.get_session_state = MagicMock(return_value=MagicMock(turn_count=0))

    gateway = AutomationCoreGateway(core, policy=SessionCutPolicy(idle_timeout_minutes=0, daily_cutoff_hour=4))
    changed = await gateway.expire_session_if_needed(reason="idle_timeout")

    assert changed is True
    core.finalize_session.assert_awaited_once()
    core.reset_session.assert_called_once()


@pytest.mark.asyncio
async def test_gateway_expire_still_resets_when_finalize_fails():
    core = AsyncMock()
    core.finalize_session = AsyncMock(side_effect=RuntimeError("boom"))
    core.reset_session = MagicMock()
    core.run_turn = AsyncMock(return_value=AgentRunResult(output_text="ok"))
    core.get_session_state = MagicMock(return_value=MagicMock(turn_count=0))

    gateway = AutomationCoreGateway(core)
    await gateway.expire_session(reason="manual")

    core.finalize_session.assert_awaited_once()
    core.reset_session.assert_called_once()


@pytest.mark.asyncio
async def test_gateway_inject_message_forwards_command_metadata():
    core = AsyncMock()
    core.run_turn = AsyncMock(return_value=AgentRunResult(output_text="ok"))
    core.get_session_state = MagicMock(return_value=MagicMock(turn_count=0))

    gateway = AutomationCoreGateway(core, session_id="cli:default")
    await gateway.inject_message(
        command=InjectMessageCommand(
            session_id="wechat:user-1",
            input=AgentRunInput(text="hello", metadata={"from_input": "1"}),
            metadata={"from_command": "2"},
        ),
        hooks=AgentHooks(),
    )

    call = core.run_turn.await_args
    assert call.args[0].metadata["session_id"] == "wechat:user-1"
    assert call.args[0].metadata["from_input"] == "1"
    assert call.args[0].metadata["from_command"] == "2"
