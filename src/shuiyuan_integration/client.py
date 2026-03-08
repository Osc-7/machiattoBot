"""
水源社区 Discourse API 客户端。

使用 User-Api-Key 访问水源社区（https://shuiyuan.sjtu.edu.cn）。
参考 ShuiyuanAutoReply：请求间保持最小间隔，降低 429 限流风险。
"""

import threading
import time
from typing import Any, Optional

import requests

SITE_URL_BASE = "https://shuiyuan.sjtu.edu.cn"

# 类级请求节流：所有 ShuiyuanClient 实例共享，避免多路复用造成 429
_request_lock: threading.Lock = threading.Lock()
_last_request_ts: float = 0.0
_request_interval: float = 1.2  # 秒，略大于 ShuiyuanAutoReply 的 1.0，更稳妥


def _ensure_rate_limit() -> None:
    """请求前等待，保证与上次请求间隔至少 _request_interval 秒。"""
    global _last_request_ts
    with _request_lock:
        elapsed = time.monotonic() - _last_request_ts
        if elapsed < _request_interval:
            time.sleep(_request_interval - elapsed)
        _last_request_ts = time.monotonic()


class ShuiyuanClient:
    """
    水源社区 API 客户端。

    使用 User-Api-Key 认证，支持搜索、获取话题/帖子等只读操作。
    """

    def __init__(
        self,
        user_api_key: str,
        site_url: str = SITE_URL_BASE,
        timeout: float = 10.0,
    ):
        self._base = site_url.rstrip("/")
        self._headers = {"User-Api-Key": user_api_key}
        self._timeout = timeout

    def search(
        self,
        q: str,
        page: int = 1,
    ) -> dict[str, Any]:
        """
        搜索水源社区。

        Args:
            q: 搜索关键词，支持 Discourse 语法如 tags:水源开发者
            page: 页码，默认 1

        Returns:
            Discourse search 接口返回的 JSON 字典
        """
        _ensure_rate_limit()
        r = requests.get(
            f"{self._base}/search.json",
            params={"q": q, "page": page},
            headers=self._headers,
            timeout=self._timeout,
        )
        r.raise_for_status()
        return r.json()

    def get_topic(self, topic_id: int) -> Optional[dict[str, Any]]:
        """
        获取单个话题详情。

        Args:
            topic_id: 话题 ID

        Returns:
            话题 JSON 字典，不存在则 None
        """
        _ensure_rate_limit()
        r = requests.get(
            f"{self._base}/t/{topic_id}.json",
            headers=self._headers,
            timeout=self._timeout,
        )
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()

    def get_topic_posts(
        self,
        topic_id: int,
        post_ids: Optional[list[int]] = None,
    ) -> Optional[dict[str, Any]]:
        """
        获取话题下的帖子列表。

        Args:
            topic_id: 话题 ID
            post_ids: 可选，指定要获取的帖子 ID 列表（最多 20 个）

        Returns:
            帖子列表 JSON 字典，不存在则 None
        """
        _ensure_rate_limit()
        url = f"{self._base}/t/{topic_id}/posts.json"
        if post_ids:
            if len(post_ids) > 20:
                post_ids = post_ids[:20]
            params = [("post_ids[]", pid) for pid in post_ids]
            r = requests.get(url, params=params, headers=self._headers, timeout=self._timeout)
        else:
            r = requests.get(url, headers=self._headers, timeout=self._timeout)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()

    def get_topic_recent_posts(
        self,
        topic_id: int,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """
        获取话题下最近 N 条帖子（按楼层顺序）。

        Discourse 单次请求最多 20 条，会分批获取。
        """
        topic = self.get_topic(topic_id)
        if not topic:
            return []
        stream = topic.get("post_stream", {}).get("stream") or []
        if not stream:
            return []
        post_ids = stream[-limit:] if len(stream) > limit else stream
        all_posts: list[dict[str, Any]] = []
        batch_size = 20
        for i in range(0, len(post_ids), batch_size):
            batch = post_ids[i : i + batch_size]
            data = self.get_topic_posts(topic_id, post_ids=batch)
            if data:
                posts = data.get("post_stream", {}).get("posts") or []
                all_posts.extend(posts)
        return sorted(all_posts, key=lambda p: p.get("post_number", 0))

    def get_user_actions(
        self,
        username: str,
        *,
        filter_type: int = 7,
        offset: int = 0,
        limit: int = 60,
        acting_username: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        获取用户操作流（如 @ 提及）。

        参照 ShuiyuanAutoReply：使用 user_actions.json，filter=7 表示 mentions。
        acting_username：可选，限定「谁做的动作」。自 @ 时 acting_user=target_user，传 acting_username=owner 可显式获取自 @。
        返回按时间倒序（ newest first），便于 stream diff 只处理新项。
        """
        params: dict[str, Any] = {
            "username": username,
            "filter": filter_type,
            "offset": offset,
        }
        if acting_username:
            params["acting_username"] = acting_username
        _ensure_rate_limit()
        r = requests.get(
            f"{self._base}/user_actions.json",
            params=params,
            headers=self._headers,
            timeout=self._timeout,
        )
        if r.status_code == 429:
            raise RuntimeError("水源 API 限流(429)，请稍后重试")
        r.raise_for_status()
        return r.json()

    def get_notifications(self, limit: int = 30, offset: int = 0) -> dict[str, Any]:
        """
        获取当前用户的通知（含 @ 提及等）。

        User-Api-Key 以当前用户身份请求，返回该用户收到的通知。
        notification_type: 1=mentioned, 2=replied, 3=quoted, ...
        """
        _ensure_rate_limit()
        r = requests.get(
            f"{self._base}/notifications.json",
            params={"limit": limit, "offset": offset},
            headers=self._headers,
            timeout=self._timeout,
        )
        if r.status_code == 429:
            raise RuntimeError("水源 API 限流(429)，请稍后重试")
        r.raise_for_status()
        return r.json()

    def get_post_by_id(
        self, topic_id: int, post_id: int
    ) -> Optional[dict[str, Any]]:
        """根据 post_id 直接获取单条帖子（含 raw 正文）。用于长帖，不依赖 stream 分页。"""
        data = self.get_topic_posts(topic_id, post_ids=[post_id])
        if not data:
            return None
        posts = data.get("post_stream", {}).get("posts") or []
        return posts[0] if posts else None

    def get_post_by_number(
        self, topic_id: int, post_number: int
    ) -> Optional[dict[str, Any]]:
        """根据楼层号获取单条帖子（依赖 topic stream，长帖可能失败，优先用 get_post_by_id）。"""
        topic = self.get_topic(topic_id)
        if not topic:
            return None
        stream = topic.get("post_stream", {}).get("stream") or []
        if post_number < 1 or post_number > len(stream):
            return None
        post_id = int(stream[post_number - 1])
        return self.get_post_by_id(topic_id, post_id)

    def create_post(
        self,
        raw: str,
        topic_id: int,
        reply_to_post_number: Optional[int] = None,
    ) -> tuple[Optional[dict[str, Any]], int, str]:
        """
        创建帖子或回复。需要 User-Api-Key 含 write scope。

        Returns:
            (post_dict, status_code, error_detail)
            - 成功: (post_dict, 200|201, "")
            - 失败: (None, status_code, error_detail)，error_detail 含响应体摘要
        """
        payload: dict[str, Any] = {"raw": raw, "topic_id": topic_id}
        if reply_to_post_number is not None:
            payload["reply_to_post_number"] = reply_to_post_number

        _ensure_rate_limit()
        r = requests.post(
            f"{self._base}/posts.json",
            json=payload,
            headers={**self._headers, "Content-Type": "application/json"},
            timeout=self._timeout,
        )
        if r.status_code in (200, 201):
            return r.json(), r.status_code, ""

        try:
            body = (r.text or "")[:500].replace("\n", " ").strip()
        except Exception:
            body = ""

        return None, r.status_code, body
