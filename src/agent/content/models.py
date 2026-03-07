"""内容引用模型：与前端解耦的统一协议。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict


@dataclass
class ContentReference:
    """
    统一的内容引用，与具体前端解耦。

    前端适配器将原始消息（如飞书 image_key、本地路径、URL）解析为 ContentReference，
    由 ContentResolver 根据 source 选择对应实现，解析为 LLM-ready content item。
    """

    source: str  # "feishu" | "local" | "url"
    ref_type: str  # "image" | "video" | "audio" | "document"
    key: str  # image_key / file_key / path / url
    extra: Dict[str, Any] | None = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "ref_type": self.ref_type,
            "key": self.key,
            "extra": self.extra or {},
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> ContentReference:
        if isinstance(d, ContentReference):
            return d
        return cls(
            source=str(d.get("source", "local")),
            ref_type=str(d.get("ref_type", "image")),
            key=str(d.get("key", "")),
            extra=d.get("extra"),
        )
