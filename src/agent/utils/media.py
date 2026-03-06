"""
多模态媒体辅助函数。

用于将本地图片/视频文件转换为可注入 OpenAI 兼容 messages 的 content item。
"""

from __future__ import annotations

import base64
import mimetypes
from pathlib import Path
from typing import Any, Dict, Optional, Tuple


def _project_root() -> Path:
    # /work/src/schedule_agent/utils/media.py -> /work
    return Path(__file__).resolve().parents[3]


def _resolve_media_path(media_path: str) -> Path:
    """
    将媒体路径解析为绝对路径。

    解析策略：
    1) 绝对路径：直接使用
    2) 相对路径（如 user_file/a.png）：相对于项目根目录
    3) 仅文件名（如 a.png）：默认在项目根目录的 user_file/ 下查找
    """
    raw = (media_path or "").strip()
    p = Path(raw).expanduser()
    if p.is_absolute():
        return p.resolve()

    root = _project_root()
    direct = (root / p).resolve()
    if direct.exists():
        return direct

    return (root / "user_file" / p).resolve()


def _file_to_data_url(path: Path) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    将文件编码为 data URL。

    Returns:
        (data_url, mime, error)
    """
    if not path.exists() or not path.is_file():
        return None, None, f"媒体文件不存在: {path}"

    mime, _ = mimetypes.guess_type(str(path))
    if not mime:
        mime = "application/octet-stream"

    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}", mime, None


def resolve_media_to_content_item(
    media_path: str,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    将媒体路径转换为多模态 content item（image_url / video_url）。

    Returns:
        (content_item, error)
    """
    path = _resolve_media_path(media_path)
    data_url, mime, err = _file_to_data_url(path)
    if err:
        return None, err

    if (mime or "").startswith("video/"):
        return {"type": "video_url", "video_url": {"url": data_url}}, None

    # 默认按图片处理（包含未知 mime 的兜底）
    return {"type": "image_url", "image_url": {"url": data_url}}, None
