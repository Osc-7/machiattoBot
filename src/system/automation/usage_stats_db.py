"""SQLite-backed daily per-model LLM token usage stats."""

from __future__ import annotations

import os
import sqlite3
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

DEFAULT_TIMEZONE = "Asia/Shanghai"

_usage_stats_db: Optional["UsageStatsDB"] = None


def _default_db_path() -> Path:
    test_dir = os.environ.get("SCHEDULE_AGENT_TEST_DATA_DIR")
    if test_dir:
        return Path(test_dir) / "automation" / "usage_stats.db"
    return Path("data") / "automation" / "usage_stats.db"


def set_usage_stats_db(db: Optional["UsageStatsDB"]) -> None:
    """Inject the process-wide UsageStatsDB singleton (daemon startup)."""
    global _usage_stats_db
    _usage_stats_db = db


def get_usage_stats_db() -> Optional["UsageStatsDB"]:
    """Return the process-wide UsageStatsDB, or None if not injected."""
    return _usage_stats_db


class UsageStatsDB:
    """
    Persist LLM token usage aggregated by (day, provider_key, api_model).

    Day boundaries use Asia/Shanghai by default. Writes are additive
    (INSERT ... ON CONFLICT DO UPDATE). Queries return a chart-friendly
    nested structure: summary + days[] with per-model breakdown.
    """

    def __init__(
        self,
        db_path: Optional[str] = None,
        *,
        timezone: str = DEFAULT_TIMEZONE,
    ) -> None:
        self._db_path = Path(db_path) if db_path else _default_db_path()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._tz = ZoneInfo(timezone)
        self._timezone_name = timezone
        self._init_db()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS usage_daily (
                    day TEXT NOT NULL,
                    provider_key TEXT NOT NULL,
                    api_model TEXT NOT NULL,
                    prompt_tokens INTEGER NOT NULL DEFAULT 0,
                    completion_tokens INTEGER NOT NULL DEFAULT 0,
                    total_tokens INTEGER NOT NULL DEFAULT 0,
                    cache_hit_tokens INTEGER NOT NULL DEFAULT 0,
                    cache_miss_tokens INTEGER NOT NULL DEFAULT 0,
                    call_count INTEGER NOT NULL DEFAULT 0,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (day, provider_key, api_model)
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_usage_daily_day ON usage_daily(day)"
            )

    def today(self) -> str:
        """Return today's date string in the configured timezone."""
        return datetime.now(self._tz).date().isoformat()

    def resolve_range(
        self,
        *,
        range: Optional[str] = None,
        from_day: Optional[str] = None,
        to_day: Optional[str] = None,
    ) -> tuple[str, str]:
        """
        Resolve a query window to inclusive (from_day, to_day) YYYY-MM-DD.

        Presets: ``7d`` (default), ``30d``, ``today``. Explicit from/to
        override the preset when both are provided; a lone from or to
        is filled with today / the other bound.
        """
        today = date.fromisoformat(self.today())
        preset = (range or "").strip().lower() or None

        if from_day and to_day:
            return from_day, to_day

        if from_day and not to_day:
            return from_day, today.isoformat()
        if to_day and not from_day:
            return to_day, to_day

        if preset in (None, "7d", "last_7_days", "week"):
            start = today - timedelta(days=6)
            return start.isoformat(), today.isoformat()
        if preset in ("30d", "last_30_days", "month"):
            start = today - timedelta(days=29)
            return start.isoformat(), today.isoformat()
        if preset in ("today", "1d"):
            return today.isoformat(), today.isoformat()

        raise ValueError(f"unsupported range preset: {range!r}")

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def record(
        self,
        *,
        provider_key: str,
        api_model: str,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_tokens: Optional[int] = None,
        cache_hit_tokens: int = 0,
        cache_miss_tokens: int = 0,
        call_count: int = 1,
        day: Optional[str] = None,
    ) -> None:
        """Accumulate one LLM call into the daily bucket."""
        pk = (provider_key or "").strip() or "unknown"
        am = (api_model or "").strip() or "unknown"
        day_s = (day or self.today()).strip()
        pt = max(0, int(prompt_tokens or 0))
        ct = max(0, int(completion_tokens or 0))
        tt = int(total_tokens) if total_tokens is not None else pt + ct
        tt = max(0, tt)
        hit = max(0, int(cache_hit_tokens or 0))
        miss = max(0, int(cache_miss_tokens or 0))
        calls = max(0, int(call_count or 0))
        now = time.time()

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO usage_daily (
                    day, provider_key, api_model,
                    prompt_tokens, completion_tokens, total_tokens,
                    cache_hit_tokens, cache_miss_tokens, call_count, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(day, provider_key, api_model) DO UPDATE SET
                    prompt_tokens = prompt_tokens + excluded.prompt_tokens,
                    completion_tokens = completion_tokens + excluded.completion_tokens,
                    total_tokens = total_tokens + excluded.total_tokens,
                    cache_hit_tokens = cache_hit_tokens + excluded.cache_hit_tokens,
                    cache_miss_tokens = cache_miss_tokens + excluded.cache_miss_tokens,
                    call_count = call_count + excluded.call_count,
                    updated_at = excluded.updated_at
                """,
                (day_s, pk, am, pt, ct, tt, hit, miss, calls, now),
            )

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def query(
        self,
        *,
        range: Optional[str] = None,
        from_day: Optional[str] = None,
        to_day: Optional[str] = None,
        provider_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Return chart-friendly usage for an inclusive day range.

        Shape: ``{timezone, from_day, to_day, summary, model_keys, days}``.
        Every calendar day in the closed interval appears in ``days``
        (empty days have total_tokens=0 and models=[]).
        """
        start_s, end_s = self.resolve_range(
            range=range, from_day=from_day, to_day=to_day
        )
        start = date.fromisoformat(start_s)
        end = date.fromisoformat(end_s)
        if end < start:
            start, end = end, start
            start_s, end_s = start.isoformat(), end.isoformat()

        pk_filter = (provider_key or "").strip() or None
        with self._connect() as conn:
            if pk_filter:
                rows = conn.execute(
                    """
                    SELECT day, provider_key, api_model,
                           prompt_tokens, completion_tokens, total_tokens,
                           cache_hit_tokens, cache_miss_tokens, call_count
                    FROM usage_daily
                    WHERE day >= ? AND day <= ? AND provider_key = ?
                    ORDER BY day ASC, total_tokens DESC
                    """,
                    (start_s, end_s, pk_filter),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT day, provider_key, api_model,
                           prompt_tokens, completion_tokens, total_tokens,
                           cache_hit_tokens, cache_miss_tokens, call_count
                    FROM usage_daily
                    WHERE day >= ? AND day <= ?
                    ORDER BY day ASC, total_tokens DESC
                    """,
                    (start_s, end_s),
                ).fetchall()

        by_day: Dict[str, List[sqlite3.Row]] = {}
        model_totals: Dict[str, int] = {}
        for row in rows:
            d = str(row["day"])
            by_day.setdefault(d, []).append(row)
            pk = str(row["provider_key"])
            model_totals[pk] = model_totals.get(pk, 0) + int(row["total_tokens"] or 0)

        model_keys = sorted(model_totals.keys(), key=lambda k: (-model_totals[k], k))

        zero_summary = {
            "total_tokens": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "cache_hit_tokens": 0,
            "cache_miss_tokens": 0,
            "call_count": 0,
        }
        summary = dict(zero_summary)
        days_out: List[Dict[str, Any]] = []

        cur = start
        while cur <= end:
            day_s = cur.isoformat()
            day_rows = by_day.get(day_s, [])
            day_totals = dict(zero_summary)
            models: List[Dict[str, Any]] = []
            for row in day_rows:
                entry = {
                    "provider_key": str(row["provider_key"]),
                    "api_model": str(row["api_model"]),
                    "prompt_tokens": int(row["prompt_tokens"] or 0),
                    "completion_tokens": int(row["completion_tokens"] or 0),
                    "total_tokens": int(row["total_tokens"] or 0),
                    "cache_hit_tokens": int(row["cache_hit_tokens"] or 0),
                    "cache_miss_tokens": int(row["cache_miss_tokens"] or 0),
                    "call_count": int(row["call_count"] or 0),
                }
                models.append(entry)
                for k in zero_summary:
                    day_totals[k] += entry[k]
            days_out.append({"day": day_s, **day_totals, "models": models})
            for k in zero_summary:
                summary[k] += day_totals[k]
            cur += timedelta(days=1)

        return {
            "timezone": self._timezone_name,
            "from_day": start_s,
            "to_day": end_s,
            "summary": summary,
            "model_keys": model_keys,
            "days": days_out,
        }


def format_usage_stats_text(data: Dict[str, Any]) -> str:
    """Human-readable console dump of a ``query()`` result."""
    if not data.get("available", True) and data.get("message"):
        return str(data["message"])

    from_day = data.get("from_day", "?")
    to_day = data.get("to_day", "?")
    tz = data.get("timezone", DEFAULT_TIMEZONE)
    summary = data.get("summary") or {}
    lines = [
        f"usage {from_day}..{to_day} ({tz})",
        (
            f"summary: total={int(summary.get('total_tokens', 0)):,}  "
            f"calls={int(summary.get('call_count', 0)):,}"
        ),
    ]
    for day in data.get("days") or []:
        if not isinstance(day, dict):
            continue
        lines.append(
            f"{day.get('day')}  total={int(day.get('total_tokens', 0)):,}"
        )
        for m in day.get("models") or []:
            if not isinstance(m, dict):
                continue
            pk = m.get("provider_key") or "?"
            am = m.get("api_model") or "?"
            lines.append(f"  {pk} ({am}): {int(m.get('total_tokens', 0)):,}")
    return "\n".join(lines)
