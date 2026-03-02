"""Stub email connector."""

from __future__ import annotations

from datetime import datetime, timedelta

from .base import BaseConnector, ConnectorFetchItem, ConnectorFetchResult
from zoneinfo import ZoneInfo

class EmailConnectorStub(BaseConnector):
    source_type = "email"

    async def fetch(self, since_cursor: str | None, account_id: str = "default") -> ConnectorFetchResult:

        timezone = ZoneInfo("Asia/Shanghai")
        now = datetime.now(timezone)
        # 暂时关闭邮件同步：不返回任何待写入的外部条目
        next_cursor = since_cursor or now.isoformat()
        return ConnectorFetchResult(items=[], next_cursor=next_cursor)
