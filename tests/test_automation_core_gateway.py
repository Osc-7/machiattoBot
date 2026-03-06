"""AutomationCoreGateway tests."""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.automation import AutomationCoreGateway, SessionCutPolicy, SessionRegistry
from agent.core.interfaces import AgentHooks, AgentRunInput, AgentRunResult, InjectMessageCommand


@pytest.mark.asyncio
async def test_gateway_dispatches_run_turn_and_updates_activity(tmp_path):
    core = AsyncMock()
    core.run_turn = AsyncMock(return_value=AgentRunResult(output_text="ok"))
    core.get_session_state = MagicMock(return_value=MagicMock(turn_count=1))
    core.get_token_usage = MagicMock(return_value={"total_tokens": 3})

    gateway = AutomationCoreGateway(
        core,
        session_id="cli:default",
        session_registry=SessionRegistry(str(tmp_path / "sessions.db")),
    )
    result = await gateway.run_turn(AgentRunInput(text="hello"), hooks=AgentHooks())

    assert result.output_text == "ok"
    core.run_turn.assert_awaited_once()
    call = core.run_turn.await_args
    assert call.args[0].text == "hello"
    assert call.args[0].metadata["session_id"] == "cli:default"


@pytest.mark.asyncio
async def test_gateway_expire_flow_calls_finalize_then_reset(tmp_path):
    core = AsyncMock()
    core.finalize_session = AsyncMock(return_value=None)
    core.reset_session = MagicMock()
    core.activate_session = AsyncMock(return_value=None)
    core.run_turn = AsyncMock(return_value=AgentRunResult(output_text="ok"))
    core.get_session_state = MagicMock(return_value=MagicMock(turn_count=0))

    gateway = AutomationCoreGateway(
        core,
        policy=SessionCutPolicy(idle_timeout_minutes=0, daily_cutoff_hour=4),
        session_registry=SessionRegistry(str(tmp_path / "sessions.db")),
    )
    changed = await gateway.expire_session_if_needed(reason="idle_timeout")

    assert changed is True
    core.finalize_session.assert_awaited_once()
    core.reset_session.assert_called_once()
    core.activate_session.assert_awaited_once_with("cli:default", replay_messages_limit=0)


@pytest.mark.asyncio
async def test_gateway_expire_still_resets_when_finalize_fails(tmp_path):
    core = AsyncMock()
    core.finalize_session = AsyncMock(side_effect=RuntimeError("boom"))
    core.reset_session = MagicMock()
    core.activate_session = AsyncMock(return_value=None)
    core.run_turn = AsyncMock(return_value=AgentRunResult(output_text="ok"))
    core.get_session_state = MagicMock(return_value=MagicMock(turn_count=0))

    gateway = AutomationCoreGateway(core, session_registry=SessionRegistry(str(tmp_path / "sessions.db")))
    await gateway.expire_session(reason="manual")

    core.finalize_session.assert_awaited_once()
    core.reset_session.assert_called_once()
    core.activate_session.assert_awaited_once_with("cli:default", replay_messages_limit=0)


@pytest.mark.asyncio
async def test_gateway_inject_message_forwards_command_metadata(tmp_path):
    core = AsyncMock()
    core.run_turn = AsyncMock(return_value=AgentRunResult(output_text="default"))
    core.get_session_state = MagicMock(return_value=MagicMock(turn_count=0))

    core_external = AsyncMock()
    core_external.run_turn = AsyncMock(return_value=AgentRunResult(output_text="ok"))
    core_external.get_session_state = MagicMock(return_value=MagicMock(turn_count=0))
    factory = AsyncMock(return_value=core_external)

    gateway = AutomationCoreGateway(
        core,
        session_id="cli:default",
        session_factory=factory,
        session_registry=SessionRegistry(str(tmp_path / "sessions.db")),
    )
    await gateway.inject_message(
        command=InjectMessageCommand(
            session_id="wechat:user-1",
            input=AgentRunInput(text="hello", metadata={"from_input": "1", "trace_id": "input", "session_id": "bad-input"}),
            metadata={"from_command": "2", "trace_id": "command", "session_id": "bad-command"},
        ),
        hooks=AgentHooks(),
    )

    call = core_external.run_turn.await_args
    assert call.args[0].metadata["session_id"] == "wechat:user-1"
    assert call.args[0].metadata["from_input"] == "1"
    assert call.args[0].metadata["from_command"] == "2"
    assert call.args[0].metadata["trace_id"] == "command"


@pytest.mark.asyncio
async def test_gateway_switch_session_creates_and_routes_to_new_core(tmp_path):
    core_default = AsyncMock()
    core_default.run_turn = AsyncMock(return_value=AgentRunResult(output_text="default"))
    core_default.get_session_state = MagicMock(return_value=MagicMock(turn_count=0))

    created_core = AsyncMock()
    created_core.run_turn = AsyncMock(return_value=AgentRunResult(output_text="new"))
    created_core.get_session_state = MagicMock(return_value=MagicMock(turn_count=0))
    created_core.activate_session = AsyncMock(return_value=None)
    factory = AsyncMock(return_value=created_core)

    gateway = AutomationCoreGateway(
        core_default,
        session_id="cli:default",
        session_factory=factory,
        session_registry=SessionRegistry(str(tmp_path / "sessions.db")),
    )
    created = await gateway.switch_session("cli:work")
    result = await gateway.run_turn(AgentRunInput(text="hello"), hooks=AgentHooks())

    assert created is True
    assert result.output_text == "new"
    factory.assert_awaited_once_with("cli:work")
    created_core.activate_session.assert_awaited_once_with("cli:work", replay_messages_limit=0)
    created_core.run_turn.assert_awaited_once()
    assert "cli:default" in gateway.list_sessions()
    assert "cli:work" in gateway.list_sessions()


@pytest.mark.asyncio
async def test_gateway_inject_message_uses_target_session_without_switching_active(tmp_path):
    core_default = AsyncMock()
    core_default.run_turn = AsyncMock(return_value=AgentRunResult(output_text="default"))
    core_default.get_session_state = MagicMock(return_value=MagicMock(turn_count=0))

    created_core = AsyncMock()
    created_core.run_turn = AsyncMock(return_value=AgentRunResult(output_text="other"))
    created_core.get_session_state = MagicMock(return_value=MagicMock(turn_count=0))
    factory = AsyncMock(return_value=created_core)

    gateway = AutomationCoreGateway(
        core_default,
        session_id="cli:default",
        session_factory=factory,
        session_registry=SessionRegistry(str(tmp_path / "sessions.db")),
    )
    await gateway.inject_message(
        InjectMessageCommand(session_id="wx:u1", input=AgentRunInput(text="push")),
        hooks=AgentHooks(),
    )
    result = await gateway.run_turn(AgentRunInput(text="local"), hooks=AgentHooks())

    assert gateway.active_session_id == "cli:default"
    assert result.output_text == "default"
    created_core.run_turn.assert_awaited_once()
    core_default.run_turn.assert_awaited_once()


@pytest.mark.asyncio
async def test_gateway_close_only_closes_owned_sessions(tmp_path):
    core_default = AsyncMock()
    core_default.get_session_state = MagicMock(return_value=MagicMock(turn_count=0))
    core_default.run_turn = AsyncMock(return_value=AgentRunResult(output_text="default"))
    core_default.close = AsyncMock()

    created_core = AsyncMock()
    created_core.get_session_state = MagicMock(return_value=MagicMock(turn_count=0))
    created_core.run_turn = AsyncMock(return_value=AgentRunResult(output_text="new"))
    created_core.close = AsyncMock()
    factory = AsyncMock(return_value=created_core)

    gateway = AutomationCoreGateway(
        core_default,
        session_id="cli:default",
        session_factory=factory,
        session_registry=SessionRegistry(str(tmp_path / "sessions.db")),
    )
    await gateway.switch_session("cli:work")
    await gateway.close()

    core_default.close.assert_not_awaited()
    created_core.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_gateway_sessions_visible_across_instances(tmp_path):
    db_path = str(tmp_path / "sessions.db")
    core_a = AsyncMock()
    core_a.run_turn = AsyncMock(return_value=AgentRunResult(output_text="a"))
    core_a.get_session_state = MagicMock(return_value=MagicMock(turn_count=0))
    core_a2 = AsyncMock()
    core_a2.run_turn = AsyncMock(return_value=AgentRunResult(output_text="a2"))
    core_a2.get_session_state = MagicMock(return_value=MagicMock(turn_count=0))
    factory = AsyncMock(return_value=core_a2)

    core_b = AsyncMock()
    core_b.run_turn = AsyncMock(return_value=AgentRunResult(output_text="b"))
    core_b.get_session_state = MagicMock(return_value=MagicMock(turn_count=0))

    gw_a = AutomationCoreGateway(
        core_a,
        session_id="cli:default",
        session_registry=SessionRegistry(db_path),
        owner_id="root",
        source="cli",
        session_factory=factory,
    )
    await gw_a.switch_session("cli:work")
    await gw_a.close()

    gw_b = AutomationCoreGateway(
        core_b,
        session_id="cli:default",
        session_registry=SessionRegistry(db_path),
        owner_id="root",
        source="cli",
    )
    sessions = gw_b.list_sessions()
    await gw_b.close()

    assert "cli:default" in sessions
    assert "cli:work" in sessions


@pytest.mark.asyncio
async def test_gateway_should_expire_uses_registry_timestamp_for_unloaded_session(tmp_path):
    db_path = str(tmp_path / "sessions.db")
    registry = SessionRegistry(db_path)
    registry.upsert_session("root", "cli", "cli:stale")
    stale_ts = (datetime.utcnow() - timedelta(minutes=120)).isoformat()
    registry._conn.execute(  # type: ignore[attr-defined]
        "UPDATE sessions SET updated_at=? WHERE owner_id=? AND source=? AND session_id=?",
        (stale_ts, "root", "cli", "cli:stale"),
    )
    registry._conn.commit()  # type: ignore[attr-defined]

    core = AsyncMock()
    core.run_turn = AsyncMock(return_value=AgentRunResult(output_text="ok"))
    core.get_session_state = MagicMock(return_value=MagicMock(turn_count=0))

    gateway = AutomationCoreGateway(
        core,
        session_id="cli:default",
        policy=SessionCutPolicy(idle_timeout_minutes=30, daily_cutoff_hour=4),
        session_registry=registry,
        owner_id="root",
        source="cli",
    )
    assert gateway.should_expire_session("cli:stale") is True
    await gateway.close()


@pytest.mark.asyncio
async def test_gateway_expired_session_not_repeated_until_activity(tmp_path):
    registry = SessionRegistry(str(tmp_path / "sessions.db"))
    core = AsyncMock()
    core.finalize_session = AsyncMock(return_value=None)
    core.reset_session = MagicMock()
    core.activate_session = AsyncMock(return_value=None)
    core.run_turn = AsyncMock(return_value=AgentRunResult(output_text="ok"))
    core.get_session_state = MagicMock(return_value=MagicMock(turn_count=0))

    gateway = AutomationCoreGateway(
        core,
        session_id="cli:default",
        policy=SessionCutPolicy(idle_timeout_minutes=0, daily_cutoff_hour=4),
        session_registry=registry,
    )
    changed_1 = await gateway.expire_session_if_needed(reason="idle")
    changed_2 = await gateway.expire_session_if_needed(reason="idle")
    assert changed_1 is True
    assert changed_2 is False

    # 一旦有新活动（如切换/消息），会解冻，后续可再次按规则过期
    gateway.mark_activity("cli:default")
    changed_3 = await gateway.expire_session_if_needed(reason="idle")
    assert changed_3 is True
    await gateway.close()


@pytest.mark.asyncio
async def test_gateway_expire_unloaded_session_marks_only_without_finalize(tmp_path):
    core_default = AsyncMock()
    core_default.run_turn = AsyncMock(return_value=AgentRunResult(output_text="default"))
    core_default.get_session_state = MagicMock(return_value=MagicMock(turn_count=0))

    created_core = AsyncMock()
    created_core.finalize_session = AsyncMock(return_value=None)
    created_core.reset_session = MagicMock()
    created_core.activate_session = AsyncMock(return_value=None)
    created_core.get_session_state = MagicMock(return_value=MagicMock(turn_count=0))
    factory = AsyncMock(return_value=created_core)

    registry = SessionRegistry(str(tmp_path / "sessions.db"))
    registry.upsert_session("root", "cli", "cli:cold")

    gateway = AutomationCoreGateway(
        core_default,
        session_id="cli:default",
        session_factory=factory,
        session_registry=registry,
        owner_id="root",
        source="cli",
    )
    await gateway.expire_session(reason="timer", session_id="cli:cold")

    factory.assert_not_awaited()
    created_core.finalize_session.assert_not_awaited()
    assert registry.is_expired("root", "cli", "cli:cold") is True
    await gateway.close()


@pytest.mark.asyncio
async def test_gateway_create_session_from_expired_registry_activates_without_replay(tmp_path):
    core_default = AsyncMock()
    core_default.run_turn = AsyncMock(return_value=AgentRunResult(output_text="default"))
    core_default.get_session_state = MagicMock(return_value=MagicMock(turn_count=0))

    created_core = AsyncMock()
    created_core.run_turn = AsyncMock(return_value=AgentRunResult(output_text="new"))
    created_core.get_session_state = MagicMock(return_value=MagicMock(turn_count=0))
    created_core.activate_session = AsyncMock(return_value=None)
    factory = AsyncMock(return_value=created_core)

    registry = SessionRegistry(str(tmp_path / "sessions.db"))
    registry.upsert_session("root", "cli", "cli:expired")
    registry.mark_expired("root", "cli", "cli:expired")

    gateway = AutomationCoreGateway(
        core_default,
        session_id="cli:default",
        session_factory=factory,
        session_registry=registry,
        owner_id="root",
        source="cli",
    )

    await gateway.switch_session("cli:expired", create_if_missing=False)
    created_core.activate_session.assert_awaited_once_with("cli:expired", replay_messages_limit=0)
    await gateway.close()


@pytest.mark.asyncio
async def test_gateway_delete_session_returns_false_when_history_delete_fails(tmp_path):
    registry = SessionRegistry(str(tmp_path / "sessions.db"))

    core_default = AsyncMock()
    core_default.run_turn = AsyncMock(return_value=AgentRunResult(output_text="default"))
    core_default.get_session_state = MagicMock(return_value=MagicMock(turn_count=0))

    broken_core = AsyncMock()
    broken_core.get_session_state = MagicMock(return_value=MagicMock(turn_count=0))
    broken_core.activate_session = AsyncMock(return_value=None)
    broken_core.delete_session_history = MagicMock(side_effect=RuntimeError("db write failed"))
    broken_core.close = AsyncMock()
    factory = AsyncMock(return_value=broken_core)

    gateway = AutomationCoreGateway(
        core_default,
        session_id="cli:default",
        session_factory=factory,
        session_registry=registry,
        owner_id="root",
        source="cli",
    )
    await gateway.ensure_session("cli:work")

    ok = await gateway.delete_session("cli:work")
    sessions = gateway.list_sessions()
    assert ok is False
    assert registry.session_exists("root", "cli", "cli:work") is True
    assert "cli:work" in sessions
    await gateway.close()


@pytest.mark.asyncio
async def test_gateway_delete_session_returns_false_without_core_session_for_cold_session(tmp_path):
    registry = SessionRegistry(str(tmp_path / "sessions.db"))
    registry.upsert_session("root", "cli", "cli:cold")

    core_default = AsyncMock()
    core_default.run_turn = AsyncMock(return_value=AgentRunResult(output_text="default"))
    core_default.get_session_state = MagicMock(return_value=MagicMock(turn_count=0))

    gateway = AutomationCoreGateway(
        core_default,
        session_id="cli:default",
        session_registry=registry,
        owner_id="root",
        source="cli",
    )

    ok = await gateway.delete_session("cli:cold")
    assert ok is False
    assert registry.session_exists("root", "cli", "cli:cold") is True
    await gateway.close()
