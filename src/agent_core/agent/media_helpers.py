"""Helpers for multimodal carry-over and outgoing attachments."""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Tuple

from agent_core.tools import ToolResult
from agent_core.utils.media import resolve_media_to_content_item


def queue_media_for_next_call(
    result: ToolResult,
    pending_multimodal_items: List[Dict[str, Any]],
    media_resolver: Callable[[str], Tuple[Dict[str, Any] | None, str | None]] = resolve_media_to_content_item,
) -> None:
    """Queue media declared by a tool result into the next LLM call payload."""
    if not result.success:
        return
    if not isinstance(result.metadata, dict):
        return
    if not result.metadata.get("embed_in_next_call"):
        return

    candidate_paths: List[str] = []
    data = result.data
    if isinstance(data, dict):
        path = data.get("path")
        if isinstance(path, str) and path.strip():
            candidate_paths.append(path.strip())
        paths = data.get("paths")
        if isinstance(paths, list):
            for item in paths:
                if isinstance(item, str) and item.strip():
                    candidate_paths.append(item.strip())

    meta_path = result.metadata.get("path")
    if isinstance(meta_path, str) and meta_path.strip():
        candidate_paths.append(meta_path.strip())
    meta_paths = result.metadata.get("paths")
    if isinstance(meta_paths, list):
        for item in meta_paths:
            if isinstance(item, str) and item.strip():
                candidate_paths.append(item.strip())

    for media_path in candidate_paths:
        content_item, _err = media_resolver(media_path)
        if content_item:
            pending_multimodal_items.append(content_item)


def collect_outgoing_attachment(
    result: ToolResult,
    outgoing_attachments: List[Dict[str, Any]],
) -> None:
    """Collect user-facing attachment metadata from tool results."""
    if not result.success or not isinstance(result.metadata, dict):
        return
    att = result.metadata.get("outgoing_attachment")
    if not att or not isinstance(att, dict):
        return
    if att.get("type") != "image":
        return
    if "path" in att or "url" in att:
        outgoing_attachments.append(dict(att))


def append_pending_multimodal_messages(
    messages: List[Dict[str, Any]],
    pending_multimodal_items: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Append pending media as one extra user multimodal message for this request only.
    """
    if not pending_multimodal_items:
        return messages

    content: List[Dict[str, Any]] = [
        {
            "type": "text",
            "text": "以下是你在上一轮工具调用中请求附加的媒体，请结合当前任务继续分析。",
        }
    ]
    content.extend(pending_multimodal_items)
    return [*messages, {"role": "user", "content": content}]
