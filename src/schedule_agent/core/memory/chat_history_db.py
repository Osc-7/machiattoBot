"""
ChatHistoryDB - 对话历史持久化数据库

使用 SQLite + FTS5 全文索引存储对话历史，支持关键词搜索和上下文翻页。
写入策略：
- user/assistant 消息：完整内容
- tool 消息：截断到 500 字并标注 [已截断]
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional


_TOOL_CONTENT_MAX = 500
_TRUNCATE_MARKER = "[已截断]"

_DDL = """
CREATE TABLE IF NOT EXISTS messages (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id   TEXT    NOT NULL,
    timestamp    TEXT    NOT NULL,
    role         TEXT    NOT NULL,
    content      TEXT    NOT NULL,
    tool_name    TEXT,
    is_truncated INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);
CREATE INDEX IF NOT EXISTS idx_messages_timestamp ON messages(timestamp);

CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    content,
    role,
    session_id,
    content='messages',
    content_rowid='id'
);

CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
    INSERT INTO messages_fts(rowid, content, role, session_id)
    VALUES (new.id, new.content, new.role, new.session_id);
END;

CREATE TRIGGER IF NOT EXISTS messages_ad AFTER DELETE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, content, role, session_id)
    VALUES ('delete', old.id, old.content, old.role, old.session_id);
END;

CREATE TRIGGER IF NOT EXISTS messages_au AFTER UPDATE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, content, role, session_id)
    VALUES ('delete', old.id, old.content, old.role, old.session_id);
    INSERT INTO messages_fts(rowid, content, role, session_id)
    VALUES (new.id, new.content, new.role, new.session_id);
END;
"""


class ChatHistoryDB:
    """SQLite + FTS5 对话历史数据库。"""

    def __init__(self, db_path: str) -> None:
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None
        self._ensure_schema()

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
        return self._conn

    @contextmanager
    def _cursor(self) -> Generator[sqlite3.Cursor, None, None]:
        conn = self._get_conn()
        cur = conn.cursor()
        try:
            yield cur
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()

    def _ensure_schema(self) -> None:
        conn = self._get_conn()
        conn.executescript(_DDL)
        conn.commit()

    @staticmethod
    def _truncate_tool_content(content: str) -> tuple[str, bool]:
        """截断工具内容，返回 (处理后内容, 是否截断)。"""
        if len(content) <= _TOOL_CONTENT_MAX:
            return content, False
        return content[:_TOOL_CONTENT_MAX] + _TRUNCATE_MARKER, True

    def write_message(
        self,
        session_id: str,
        role: str,
        content: str,
        tool_name: Optional[str] = None,
        timestamp: Optional[str] = None,
    ) -> int:
        """
        写入一条消息。

        Args:
            session_id: 会话 ID
            role: 消息角色（user | assistant | tool）
            content: 消息内容
            tool_name: 工具名（仅 role=tool 时有值）
            timestamp: ISO 8601 时间戳，默认取当前 UTC 时间

        Returns:
            新记录的 rowid
        """
        ts = timestamp or datetime.now(timezone.utc).isoformat()
        is_truncated = 0

        if role == "tool":
            content, truncated = self._truncate_tool_content(content)
            is_truncated = 1 if truncated else 0

        with self._cursor() as cur:
            cur.execute(
                """
                INSERT INTO messages (session_id, timestamp, role, content, tool_name, is_truncated)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (session_id, ts, role, content, tool_name, is_truncated),
            )
            return cur.lastrowid  # type: ignore[return-value]

    def search(
        self, query: str, top_k: int = 5
    ) -> List[Dict[str, Any]]:
        """
        FTS5 关键词搜索，返回最相关的消息片段。

        Args:
            query: 搜索关键词
            top_k: 返回条数上限

        Returns:
            消息列表，每条包含 id / timestamp / role / session_id / snippet
        """
        if not query.strip():
            return []

        # FTS5 查询需要转义特殊字符
        safe_query = _escape_fts_query(query)

        with self._cursor() as cur:
            cur.execute(
                """
                SELECT
                    m.id,
                    m.session_id,
                    m.timestamp,
                    m.role,
                    m.tool_name,
                    snippet(messages_fts, 0, '[', ']', '...', 16) AS snippet
                FROM messages_fts
                JOIN messages m ON m.id = messages_fts.rowid
                WHERE messages_fts MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (safe_query, top_k),
            )
            rows = cur.fetchall()

        return [
            {
                "id": r["id"],
                "session_id": r["session_id"],
                "timestamp": r["timestamp"],
                "role": r["role"],
                "tool_name": r["tool_name"],
                "snippet": r["snippet"],
            }
            for r in rows
        ]

    def get_context(
        self, message_id: int, n: int = 5
    ) -> List[Dict[str, Any]]:
        """
        获取指定消息前后各 n 条（同一 session 内）。

        Args:
            message_id: 中心消息 ID
            n: 前后各取几条

        Returns:
            消息列表（含中心消息，按时间顺序）
        """
        with self._cursor() as cur:
            # 先取中心消息的 session_id
            cur.execute(
                "SELECT session_id FROM messages WHERE id = ?", (message_id,)
            )
            row = cur.fetchone()
            if row is None:
                return []
            session_id = row["session_id"]

            cur.execute(
                """
                SELECT id, session_id, timestamp, role, content, tool_name, is_truncated
                FROM messages
                WHERE session_id = ?
                  AND id BETWEEN ? AND ?
                ORDER BY id
                """,
                (session_id, message_id - n, message_id + n),
            )
            rows = cur.fetchall()

        return [_row_to_dict(r) for r in rows]

    def scroll(
        self,
        message_id: int,
        direction: str = "up",
        n: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        从指定消息向上或向下翻页。

        Args:
            message_id: 锚点消息 ID
            direction: "up" 向更早翻 | "down" 向更新翻
            n: 返回条数

        Returns:
            消息列表（按时间顺序）
        """
        with self._cursor() as cur:
            cur.execute(
                "SELECT session_id FROM messages WHERE id = ?", (message_id,)
            )
            row = cur.fetchone()
            if row is None:
                return []
            session_id = row["session_id"]

            if direction == "up":
                cur.execute(
                    """
                    SELECT id, session_id, timestamp, role, content, tool_name, is_truncated
                    FROM messages
                    WHERE session_id = ? AND id < ?
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (session_id, message_id, n),
                )
                rows = list(reversed(cur.fetchall()))
            else:
                cur.execute(
                    """
                    SELECT id, session_id, timestamp, role, content, tool_name, is_truncated
                    FROM messages
                    WHERE session_id = ? AND id > ?
                    ORDER BY id ASC
                    LIMIT ?
                    """,
                    (session_id, message_id, n),
                )
                rows = cur.fetchall()

        return [_row_to_dict(r) for r in rows]

    def get_session_messages(self, session_id: str) -> List[Dict[str, Any]]:
        """获取某 session 的所有消息（按时间顺序）。"""
        with self._cursor() as cur:
            cur.execute(
                """
                SELECT id, session_id, timestamp, role, content, tool_name, is_truncated
                FROM messages
                WHERE session_id = ?
                ORDER BY id
                """,
                (session_id,),
            )
            rows = cur.fetchall()
        return [_row_to_dict(r) for r in rows]

    def close(self) -> None:
        """关闭数据库连接。"""
        if self._conn is not None:
            self._conn.close()
            self._conn = None


def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "session_id": row["session_id"],
        "timestamp": row["timestamp"],
        "role": row["role"],
        "content": row["content"],
        "tool_name": row["tool_name"],
        "is_truncated": bool(row["is_truncated"]),
    }


def _escape_fts_query(query: str) -> str:
    """简单转义 FTS5 查询中的特殊字符，防止语法错误。"""
    # FTS5 特殊字符：" ^ * ( ) -
    # 最简单的方式是用双引号包裹每个词
    words = query.split()
    escaped = []
    for w in words:
        # 去掉现有引号后用双引号包裹
        clean = w.replace('"', "")
        if clean:
            escaped.append(f'"{clean}"')
    return " ".join(escaped) if escaped else '""'
