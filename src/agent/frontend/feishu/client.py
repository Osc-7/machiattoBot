from __future__ import annotations

"""
飞书开放平台 HTTP 客户端封装。

- 发送文本消息
- 下载消息中的资源文件（图片、视频、音频、文件）
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

import json
import httpx

from .config import get_feishu_config
from .markdown_filter import filter_markdown_for_feishu


@dataclass
class _TokenCache:
    token: str
    expire_at: datetime

    @property
    def is_valid(self) -> bool:
        # 预留 60 秒缓冲，避免临界点过期
        return datetime.now(timezone.utc) < self.expire_at - timedelta(seconds=60)


class FeishuClient:
    """飞书 API 客户端（最小实现：获取 tenant_access_token + 发送文本消息）。"""

    def __init__(self, *, timeout_seconds: float = 10.0) -> None:
        cfg = get_feishu_config()
        self._cfg = cfg
        self._base_url = cfg.base_url.rstrip("/")
        self._timeout = timeout_seconds or cfg.timeout_seconds
        self._tenant_token_cache: Optional[_TokenCache] = None

    async def _get_tenant_access_token(self) -> str:
        """获取（或复用缓存的）tenant_access_token。"""
        if self._tenant_token_cache and self._tenant_token_cache.is_valid:
            return self._tenant_token_cache.token

        if not (self._cfg.app_id and self._cfg.app_secret):
            raise RuntimeError("Feishu app_id/app_secret 未配置，无法获取 tenant_access_token")

        url = f"{self._base_url}/open-apis/auth/v3/tenant_access_token/internal"
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(
                url,
                json={"app_id": self._cfg.app_id, "app_secret": self._cfg.app_secret},
            )
            resp.raise_for_status()
            data = resp.json()
        if int(data.get("code", 0)) != 0:
            raise RuntimeError(f"获取 tenant_access_token 失败: {data}")
        token = str(data.get("tenant_access_token") or "")
        expire = int(data.get("expire", 0) or data.get("expire_in", 0) or 3600)
        self._tenant_token_cache = _TokenCache(
            token=token,
            expire_at=datetime.now(timezone.utc) + timedelta(seconds=expire),
        )
        return token

    async def send_text_message(
        self,
        *,
        chat_id: str,
        text: str,
    ) -> None:
        """
        向指定 chat 发送纯文本消息。

        Args:
            chat_id: 飞书会话 chat_id
            text: 文本内容
        """
        if not chat_id:
            raise ValueError("chat_id 不能为空")
        # 统一在这里做 Markdown → 纯文本过滤，避免上层重复处理。
        safe_text = filter_markdown_for_feishu(text)

        token = await self._get_tenant_access_token()
        url = f"{self._base_url}/open-apis/im/v1/messages?receive_id_type=chat_id"
        payload = {
            "receive_id": chat_id,
            "msg_type": "text",
            "content": json.dumps({"text": safe_text}, ensure_ascii=False),
        }
        headers = {
            "Authorization": f"Bearer {token}",
        }
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
        if int(data.get("code", 0)) != 0:
            # 失败时抛出异常，由上层记录日志并向用户返回友好错误
            raise RuntimeError(f"发送飞书消息失败: {data}")

    async def download_message_resource(
        self,
        *,
        message_id: str,
        file_key: str,
        resource_type: str,
    ) -> Tuple[bytes, str]:
        """
        下载消息中的资源文件（图片、视频、音频、文件）。

        飞书接口: GET /open-apis/im/v1/messages/{message_id}/resources/{file_key}
        参考: https://open.feishu.cn/document/server-docs/im-v1/message-resource/get

        Args:
            message_id: 消息 ID
            file_key: 资源 key（图片用 image_key，文件/视频/音频用 file_key）
            resource_type: "image" 或 "file"

        Returns:
            (bytes, mime_type) 或抛出 RuntimeError
        """
        if not message_id or not file_key:
            raise ValueError("message_id 和 file_key 不能为空")
        if resource_type not in ("image", "file"):
            resource_type = "file"

        token = await self._get_tenant_access_token()
        url = (
            f"{self._base_url}/open-apis/im/v1/messages/{message_id}/resources/{file_key}"
            f"?type={resource_type}"
        )
        headers = {"Authorization": f"Bearer {token}"}

        async with httpx.AsyncClient(timeout=max(self._timeout, 60.0)) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()

        content_type = resp.headers.get("content-type", "application/octet-stream")
        mime = content_type.split(";")[0].strip() or "application/octet-stream"
        return resp.content, mime

