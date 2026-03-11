"""Runtime behavior tests for kernel scheduler/core pool."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agent_core.context import ConversationContext
from agent_core.kernel_interface import CoreProfile
from agent_core.tools import VersionedToolRegistry
from system.kernel import AgentKernel, CoreEntry, CorePool, KernelScheduler


@pytest.mark.asyncio
async def test_scheduler_ttl_does_not_evict_inflight_session() -> None:
    core_pool = SimpleNamespace(
        scan_expired=lambda: ["s1"],
        evict=AsyncMock(),
        touch=lambda _sid: None,
    )
    scheduler = KernelScheduler(
        kernel=SimpleNamespace(),  # type: ignore[arg-type]
        core_pool=core_pool,  # type: ignore[arg-type]
    )

    scheduler._inflight_sessions["s1"] = 1  # type: ignore[attr-defined]
    await scheduler._evict_expired()
    core_pool.evict.assert_not_awaited()

    scheduler._inflight_sessions["s1"] = 0  # type: ignore[attr-defined]
    await scheduler._evict_expired()
    core_pool.evict.assert_awaited_once_with("s1")


@pytest.mark.asyncio
async def test_core_pool_acquire_hot_updates_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile_old = CoreProfile.default_full(frontend_id="cli", dialog_window_id="u1")
    profile_new = CoreProfile.default_sub(
        allowed_tools=["parse_time"],
        frontend_id="wechat",
        dialog_window_id="u2",
    )
    fake_registry = object()

    captured: dict = {}

    def _fake_build_tool_registry(*, profile=None, config=None, memory_owner_id=None):  # type: ignore[no-untyped-def]
        captured["profile"] = profile
        captured["memory_owner_id"] = memory_owner_id
        return fake_registry

    monkeypatch.setattr("system.tools.build_tool_registry", _fake_build_tool_registry)

    pool = CorePool()
    fake_agent = SimpleNamespace(
        _tool_registry=VersionedToolRegistry(),
        _source="cli",
        _user_id="u1",
        _core_profile=profile_old,
        _session_id="sess-1",
    )
    pool._pool["sess-1"] = CoreEntry(agent=fake_agent, profile=profile_old)

    agent = await pool.acquire(
        "sess-1",
        source="wechat",
        user_id="u2",
        profile=profile_new,
    )

    assert agent is fake_agent
    assert fake_agent._tool_registry is fake_registry
    assert fake_agent._source == "wechat"
    assert fake_agent._user_id == "u2"
    assert fake_agent._core_profile == profile_new
    assert pool._pool["sess-1"].profile == profile_new
    assert captured["profile"] == profile_new
    assert captured["memory_owner_id"] == "u2"


@pytest.mark.asyncio
async def test_compress_context_keeps_complete_recent_turn() -> None:
    registry = VersionedToolRegistry()
    kernel = AgentKernel(tool_registry=registry)

    ctx = ConversationContext()
    ctx.messages = [
        {"role": "user", "content": "u1"},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "u2"},
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "c1",
                    "type": "function",
                    "function": {"name": "x", "arguments": "{}"},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "c1", "content": '{"ok":true}'},
        {"role": "assistant", "content": "a2"},
    ]
    agent = SimpleNamespace(_context=ctx, _summary_llm_client=None)

    summary, kept = await kernel._compress_context(agent, keep_recent_turns=1)

    assert summary == ""
    assert kept == 4
    assert [m["role"] for m in ctx.messages] == [
        "user",
        "assistant",
        "tool",
        "assistant",
    ]
    assert ctx.messages[0]["content"] == "u2"
