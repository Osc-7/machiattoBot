"""
历史 tool_result 清扫（L2）+ 超限就地二次截断。

入场截断（L1）只能限制「新写入」体积；checkpoint / 旧 bug 留下的假截断
（message 仍含整段 stdout）会继续占满窗口。整窗压缩（L3）又必须保留最近
轮次里的 tool 对，压不掉尾部巨石。

本模块：

1. ``scrub_oversized_tool_results``：对 **任意** ``role=tool``（含最近几条），
   若 content 估算 > ``max_tokens``，就地替换为短占位（保留 overflow_path）。
2. ``clear_stale_tool_results``：保留最近 ``keep_recent`` 条；更早且
   > ``min_tokens`` 的替换为短占位。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

from agent_core.memory.working_memory import estimate_tokens

logger = logging.getLogger(__name__)

_CLEARED_MARKER = "[cleared tool_result"
_SCRUBBED_MARKER = "[scrubbed oversized tool_result"


@dataclass(frozen=True)
class ClearingOutcome:
    """清扫统计。"""

    cleared: int = 0
    kept: int = 0
    skipped_small: int = 0
    skipped_already_cleared: int = 0


@dataclass(frozen=True)
class ScrubOutcome:
    """就地二次截断统计。"""

    scrubbed: int = 0
    skipped_ok: int = 0
    skipped_already: int = 0


def _content_as_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    try:
        return json.dumps(content, ensure_ascii=False, default=str)
    except Exception:
        return str(content)


def _extract_overflow_path(content_text: str) -> str:
    """从 tool content JSON / marker 文本里抠 overflow_path。"""
    text = (content_text or "").strip()
    if not text:
        return ""
    try:
        obj = json.loads(text)
    except Exception:
        obj = None
    if isinstance(obj, dict):
        data = obj.get("data")
        if isinstance(data, dict):
            path = data.get("overflow_path")
            if isinstance(path, str) and path.strip():
                return path.strip()
        meta = obj.get("metadata")
        if isinstance(meta, dict):
            ov = meta.get("_overflow")
            if isinstance(ov, dict):
                path = ov.get("overflow_path")
                if isinstance(path, str) and path.strip():
                    return path.strip()
        path = obj.get("overflow_path")
        if isinstance(path, str) and path.strip():
            return path.strip()
    # 退化：从自然语言 marker 里找常见路径片段
    for needle in (".tool_results/", "/.tool_results/"):
        idx = text.find(needle)
        if idx >= 0:
            end = idx
            while end < len(text) and text[end] not in " \n\t）)」\"'":
                end += 1
            # 回退到路径起始
            start = idx
            while start > 0 and text[start - 1] not in " \n\t：（(":
                start -= 1
            return text[start:end].strip(".,;")
    return ""


def _is_already_cleared(content_text: str) -> bool:
    t = (content_text or "").lstrip()
    return t.startswith(_CLEARED_MARKER) or t.startswith(_SCRUBBED_MARKER)


def _build_placeholder(
    *,
    tool_call_id: str,
    original_tokens: int,
    overflow_path: str,
    marker: str = _CLEARED_MARKER,
) -> str:
    path_hint = (
        f" re-fetch via overflow_path={overflow_path}"
        if overflow_path
        else " re-call tool or read prior overflow dump if any"
    )
    return (
        f"{marker} id={tool_call_id or 'unknown'}; "
        f"original~{original_tokens} tokens;{path_hint}]"
    )


def scrub_oversized_tool_results(
    messages: List[Dict[str, Any]],
    *,
    max_tokens: int,
) -> Tuple[List[Dict[str, Any]], ScrubOutcome]:
    """
    就地二次截断：**不区分新旧**，凡 tool content 估算 > ``max_tokens`` 一律 handle 化。

    用于消化 checkpoint / 旧 L1 bug 留下的假截断巨石（kept 仍达数十万 tokens）。
    """
    if not messages or not max_tokens or max_tokens <= 0:
        return messages, ScrubOutcome()

    scrubbed = 0
    skipped_ok = 0
    skipped_already = 0

    for msg in messages:
        if not isinstance(msg, dict) or msg.get("role") != "tool":
            continue
        content_text = _content_as_text(msg.get("content"))
        if _is_already_cleared(content_text):
            # 已是短占位；若异常仍超限则再砍
            tokens = estimate_tokens(content_text)
            if tokens <= max_tokens:
                skipped_already += 1
                continue
        else:
            tokens = estimate_tokens(content_text)
            if tokens <= max_tokens:
                skipped_ok += 1
                continue

        tool_call_id = str(msg.get("tool_call_id") or "")
        overflow_path = _extract_overflow_path(content_text)
        msg["content"] = _build_placeholder(
            tool_call_id=tool_call_id,
            original_tokens=tokens,
            overflow_path=overflow_path,
            marker=_SCRUBBED_MARKER,
        )
        scrubbed += 1

    if scrubbed:
        logger.info(
            "tool_result_scrub: scrubbed=%d skipped_ok=%d skipped_already=%d "
            "max_tokens=%d",
            scrubbed,
            skipped_ok,
            skipped_already,
            max_tokens,
        )

    return messages, ScrubOutcome(
        scrubbed=scrubbed,
        skipped_ok=skipped_ok,
        skipped_already=skipped_already,
    )


def clear_stale_tool_results(
    messages: List[Dict[str, Any]],
    *,
    keep_recent: int = 6,
    min_tokens: int = 2000,
) -> Tuple[List[Dict[str, Any]], ClearingOutcome]:
    """
    就地（返回同一 list）清扫陈旧 tool_result。

    Parameters
    ----------
    messages :
        对话消息列表（会原地修改 tool 消息的 content）。
    keep_recent :
        保留最近 N 条 tool 消息不改动（含已截断但仍较大的）。
    min_tokens :
        仅清扫估算 tokens 大于此值的 tool content。

    Returns
    -------
    (messages, outcome)
    """
    if not messages or keep_recent < 0:
        return messages, ClearingOutcome()

    tool_indices = [
        i for i, m in enumerate(messages) if isinstance(m, dict) and m.get("role") == "tool"
    ]
    if not tool_indices:
        return messages, ClearingOutcome()

    keep_set = set(tool_indices[-keep_recent:]) if keep_recent > 0 else set()
    cleared = 0
    skipped_small = 0
    skipped_already = 0
    kept = 0

    for idx in tool_indices:
        if idx in keep_set:
            kept += 1
            continue
        msg = messages[idx]
        content_text = _content_as_text(msg.get("content"))
        if _is_already_cleared(content_text):
            skipped_already += 1
            continue
        tokens = estimate_tokens(content_text)
        if tokens <= max(int(min_tokens), 0):
            skipped_small += 1
            continue
        tool_call_id = str(msg.get("tool_call_id") or "")
        overflow_path = _extract_overflow_path(content_text)
        msg["content"] = _build_placeholder(
            tool_call_id=tool_call_id,
            original_tokens=tokens,
            overflow_path=overflow_path,
        )
        cleared += 1

    if cleared:
        logger.info(
            "tool_result_clearing: cleared=%d kept=%d skipped_small=%d "
            "skipped_already=%d keep_recent=%d min_tokens=%d",
            cleared,
            kept,
            skipped_small,
            skipped_already,
            keep_recent,
            min_tokens,
        )

    return messages, ClearingOutcome(
        cleared=cleared,
        kept=kept,
        skipped_small=skipped_small,
        skipped_already_cleared=skipped_already,
    )


def apply_scrub_to_context(
    context: Any,
    *,
    max_tokens: int,
) -> ScrubOutcome:
    """对 context.messages 执行超限就地二次截断。"""
    messages = getattr(context, "messages", None)
    if not isinstance(messages, list):
        return ScrubOutcome()
    _, outcome = scrub_oversized_tool_results(messages, max_tokens=max_tokens)
    return outcome


def apply_clearing_to_context(
    context: Any,
    *,
    keep_recent: int = 6,
    min_tokens: int = 2000,
) -> ClearingOutcome:
    """对 ``ConversationContext``（或带 ``messages`` 列表的对象）执行清扫。"""
    messages = getattr(context, "messages", None)
    if not isinstance(messages, list):
        return ClearingOutcome()
    _, outcome = clear_stale_tool_results(
        messages, keep_recent=keep_recent, min_tokens=min_tokens
    )
    return outcome
