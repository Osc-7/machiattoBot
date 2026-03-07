"""本地文件 ContentResolver。"""

from __future__ import annotations

from typing import Any, Dict, Optional

from agent.utils.media import resolve_media_to_content_item

from ..models import ContentReference
from ..resolver import ContentResolver


class LocalContentResolver(ContentResolver):
    """将本地路径解析为 image_url / video_url content item。"""

    source = "local"

    async def resolve(self, ref: ContentReference) -> Optional[Dict[str, Any]]:
        item, err = resolve_media_to_content_item(ref.key)
        if err or not item:
            return None
        return item
