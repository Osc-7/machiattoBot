"""Tests for UsageStatsDB daily per-model token aggregation."""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import MagicMock

import pytest

from system.automation.usage_stats_db import (
    UsageStatsDB,
    format_usage_stats_text,
    get_usage_stats_db,
    set_usage_stats_db,
)
from system.kernel.terminal import KernelTerminal


@pytest.fixture
def db(tmp_path):
    return UsageStatsDB(db_path=str(tmp_path / "usage_stats.db"))


def test_record_accumulates_same_day_same_model(db: UsageStatsDB) -> None:
    db.record(
        provider_key="kimi_k3",
        api_model="k3",
        prompt_tokens=100,
        completion_tokens=10,
        day="2026-07-17",
    )
    db.record(
        provider_key="kimi_k3",
        api_model="k3",
        prompt_tokens=50,
        completion_tokens=5,
        cache_hit_tokens=20,
        day="2026-07-17",
    )
    out = db.query(from_day="2026-07-17", to_day="2026-07-17")
    assert out["summary"]["total_tokens"] == 165
    assert out["summary"]["prompt_tokens"] == 150
    assert out["summary"]["completion_tokens"] == 15
    assert out["summary"]["cache_hit_tokens"] == 20
    assert out["summary"]["call_count"] == 2
    assert len(out["days"]) == 1
    assert len(out["days"][0]["models"]) == 1
    m = out["days"][0]["models"][0]
    assert m["provider_key"] == "kimi_k3"
    assert m["total_tokens"] == 165


def test_same_day_multiple_models(db: UsageStatsDB) -> None:
    db.record(
        provider_key="kimi_k3",
        api_model="k3",
        prompt_tokens=100,
        completion_tokens=0,
        day="2026-07-17",
    )
    db.record(
        provider_key="deepseek_V4_pro",
        api_model="deepseek-v4-pro",
        prompt_tokens=200,
        completion_tokens=50,
        day="2026-07-17",
    )
    out = db.query(from_day="2026-07-17", to_day="2026-07-17")
    day = out["days"][0]
    assert day["total_tokens"] == 350
    assert day["call_count"] == 2
    assert day["total_tokens"] == sum(m["total_tokens"] for m in day["models"])
    assert set(out["model_keys"]) == {"kimi_k3", "deepseek_V4_pro"}
    # model_keys sorted by interval total desc
    assert out["model_keys"][0] == "deepseek_V4_pro"


def test_range_7d_fills_empty_days(db: UsageStatsDB) -> None:
    today = date.fromisoformat(db.today())
    mid = (today - timedelta(days=2)).isoformat()
    db.record(
        provider_key="kimi_k3",
        api_model="k3",
        prompt_tokens=10,
        completion_tokens=1,
        day=mid,
    )
    out = db.query(range="7d")
    assert len(out["days"]) == 7
    assert out["from_day"] == (today - timedelta(days=6)).isoformat()
    assert out["to_day"] == today.isoformat()
    nonempty = [d for d in out["days"] if d["total_tokens"] > 0]
    assert len(nonempty) == 1
    assert nonempty[0]["day"] == mid
    empty = [d for d in out["days"] if d["total_tokens"] == 0]
    assert all(d["models"] == [] for d in empty)
    assert out["summary"]["total_tokens"] == 11
    assert out["summary"]["total_tokens"] == sum(
        d["total_tokens"] for d in out["days"]
    )


def test_summary_equals_sum_of_days(db: UsageStatsDB) -> None:
    db.record(
        provider_key="a",
        api_model="m",
        prompt_tokens=10,
        completion_tokens=1,
        day="2026-07-10",
    )
    db.record(
        provider_key="b",
        api_model="n",
        prompt_tokens=20,
        completion_tokens=2,
        day="2026-07-12",
    )
    out = db.query(from_day="2026-07-10", to_day="2026-07-12")
    assert len(out["days"]) == 3
    assert out["summary"]["total_tokens"] == sum(d["total_tokens"] for d in out["days"])
    assert out["summary"]["call_count"] == sum(d["call_count"] for d in out["days"])
    assert set(out["model_keys"]) == {"a", "b"}


def test_provider_key_filter(db: UsageStatsDB) -> None:
    db.record(
        provider_key="kimi_k3",
        api_model="k3",
        prompt_tokens=100,
        completion_tokens=0,
        day="2026-07-17",
    )
    db.record(
        provider_key="deepseek_V4_pro",
        api_model="deepseek-v4-pro",
        prompt_tokens=200,
        completion_tokens=0,
        day="2026-07-17",
    )
    out = db.query(
        from_day="2026-07-17", to_day="2026-07-17", provider_key="kimi_k3"
    )
    assert out["summary"]["total_tokens"] == 100
    assert out["model_keys"] == ["kimi_k3"]
    assert len(out["days"][0]["models"]) == 1


def test_format_usage_stats_text(db: UsageStatsDB) -> None:
    db.record(
        provider_key="kimi_k3",
        api_model="k3",
        prompt_tokens=1000,
        completion_tokens=23,
        day="2026-07-17",
    )
    text = format_usage_stats_text(
        {"available": True, **db.query(from_day="2026-07-17", to_day="2026-07-17")}
    )
    assert "2026-07-17" in text
    assert "kimi_k3 (k3)" in text
    assert "1,023" in text


def test_singleton_set_get(tmp_path) -> None:
    set_usage_stats_db(None)
    assert get_usage_stats_db() is None
    db = UsageStatsDB(db_path=str(tmp_path / "u.db"))
    set_usage_stats_db(db)
    assert get_usage_stats_db() is db
    set_usage_stats_db(None)


def test_terminal_usage_stats_unavailable() -> None:
    pool = MagicMock()
    sched = MagicMock()
    terminal = KernelTerminal(scheduler=sched, core_pool=pool)
    out = terminal.usage_stats()
    assert out.get("available") is False


def test_terminal_usage_stats_with_db(tmp_path) -> None:
    db = UsageStatsDB(db_path=str(tmp_path / "u.db"))
    db.record(
        provider_key="kimi_k3",
        api_model="k3",
        prompt_tokens=5,
        completion_tokens=1,
        day=db.today(),
    )
    pool = MagicMock()
    sched = MagicMock()
    terminal = KernelTerminal(scheduler=sched, core_pool=pool, usage_stats_db=db)
    out = terminal.usage_stats(range="today")
    assert out.get("available") is True
    assert out["summary"]["total_tokens"] == 6
    assert len(out["days"]) == 1


def test_agent_record_usage_stats_soft_fail(tmp_path) -> None:
    from agent_core.agent.agent import AgentCore

    db = UsageStatsDB(db_path=str(tmp_path / "u.db"))
    set_usage_stats_db(db)
    try:
        agent = AgentCore.__new__(AgentCore)
        agent._session_id = "test-session"
        llm = MagicMock()
        llm.active_provider_name = "kimi_k3"
        llm.model = "k3"
        agent._llm_client = llm
        agent._record_usage_stats(
            prompt_tokens=100,
            completion_tokens=20,
            cache_hit_tokens=1,
            cache_miss_tokens=2,
        )
        out = db.query(range="today")
        assert out["summary"]["total_tokens"] == 120
        assert out["days"][0]["models"][0]["provider_key"] == "kimi_k3"
    finally:
        set_usage_stats_db(None)


def test_agent_record_usage_stats_no_db() -> None:
    from agent_core.agent.agent import AgentCore

    set_usage_stats_db(None)
    agent = AgentCore.__new__(AgentCore)
    agent._session_id = "test-session"
    llm = MagicMock()
    llm.active_provider_name = "kimi_k3"
    llm.model = "k3"
    agent._llm_client = llm
    # must not raise
    agent._record_usage_stats(prompt_tokens=1, completion_tokens=1)
