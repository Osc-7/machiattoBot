"""Persistent session registry for cross-process visibility."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional


_DDL = """
CREATE TABLE IF NOT EXISTS sessions (
    owner_id   TEXT NOT NULL,
    source     TEXT NOT NULL,
    session_id TEXT NOT NULL,
    is_expired INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (owner_id, source, session_id)
);

CREATE INDEX IF NOT EXISTS idx_sessions_owner_source
ON sessions(owner_id, source, updated_at);
"""


class SessionRegistry:
    """SQLite-backed registry for session discovery across terminals."""

    def __init__(self, db_path: str = "./data/sessions/session_registry.db") -> None:
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.executescript(_DDL)
        self._ensure_columns()
        self._conn.commit()

    def _ensure_columns(self) -> None:
        cur = self._conn.execute("PRAGMA table_info(sessions)")
        cols = {str(r[1]) for r in cur.fetchall()}
        if "is_expired" not in cols:
            self._conn.execute(
                "ALTER TABLE sessions ADD COLUMN is_expired INTEGER NOT NULL DEFAULT 0"
            )

    def upsert_session(self, owner_id: str, source: str, session_id: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            """
            INSERT INTO sessions(owner_id, source, session_id, is_expired, created_at, updated_at)
            VALUES (?, ?, ?, 0, ?, ?)
            ON CONFLICT(owner_id, source, session_id) DO UPDATE SET
                updated_at=excluded.updated_at,
                is_expired=0
            """,
            (owner_id, source, session_id, now, now),
        )
        self._conn.commit()

    def mark_expired(self, owner_id: str, source: str, session_id: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            """
            UPDATE sessions
            SET is_expired=1, updated_at=?
            WHERE owner_id=? AND source=? AND session_id=?
            """,
            (now, owner_id, source, session_id),
        )
        self._conn.commit()

    def is_expired(self, owner_id: str, source: str, session_id: str) -> bool:
        cur = self._conn.execute(
            """
            SELECT is_expired
            FROM sessions
            WHERE owner_id=? AND source=? AND session_id=?
            LIMIT 1
            """,
            (owner_id, source, session_id),
        )
        row = cur.fetchone()
        if row is None:
            return False
        try:
            return bool(int(row[0]))
        except Exception:
            return False

    def get_updated_at(
        self, owner_id: str, source: str, session_id: str
    ) -> Optional[datetime]:
        cur = self._conn.execute(
            "SELECT updated_at FROM sessions WHERE owner_id=? AND source=? AND session_id=? LIMIT 1",
            (owner_id, source, session_id),
        )
        row = cur.fetchone()
        if row is None:
            return None
        raw = str(row[0] or "").strip()
        if not raw:
            return None
        try:
            dt = datetime.fromisoformat(raw)
        except ValueError:
            return None
        if dt.tzinfo is not None:
            # 转换为本地 naive time（与 core_gateway.py 使用的 datetime.now() 一致），
            # 避免 UTC vs 本地时区混用导致 idle_seconds 计算错误（非 UTC 区域会误判过期）
            dt = dt.astimezone().replace(tzinfo=None)
        return dt

    def session_exists(self, owner_id: str, source: str, session_id: str) -> bool:
        cur = self._conn.execute(
            "SELECT 1 FROM sessions WHERE owner_id=? AND source=? AND session_id=? LIMIT 1",
            (owner_id, source, session_id),
        )
        return cur.fetchone() is not None

    def list_sessions(self, owner_id: str, source: str) -> List[str]:
        cur = self._conn.execute(
            """
            SELECT session_id
            FROM sessions
            WHERE owner_id=? AND source=? AND is_expired=0
            ORDER BY updated_at DESC
            """,
            (owner_id, source),
        )
        return [str(row[0]) for row in cur.fetchall()]

    def delete_session(self, owner_id: str, source: str, session_id: str) -> None:
        """从注册表中删除指定会话记录。

        仅影响 session 注册元数据，不删除底层对话历史或长期记忆。
        """
        self._conn.execute(
            "DELETE FROM sessions WHERE owner_id=? AND source=? AND session_id=?",
            (owner_id, source, session_id),
        )
        self._conn.commit()

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass
