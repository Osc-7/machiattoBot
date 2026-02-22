"""
记忆检索策略（Recall Policy）

在 Agent 处理用户输入前，根据策略检索相关记忆以 enrich context。
支持多路检索：短期记忆、长期记忆、内容记忆、MEMORY.md。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .types import MemoryEntry, SessionSummary


@dataclass
class RecallResult:
    """记忆检索结果。"""

    short_term: List[SessionSummary] = field(default_factory=list)
    long_term: List[MemoryEntry] = field(default_factory=list)
    content: List[Tuple[str, str]] = field(default_factory=list)
    memory_md_excerpt: str = ""

    def is_empty(self) -> bool:
        return (
            not self.short_term
            and not self.long_term
            and not self.content
            and not self.memory_md_excerpt
        )

    def to_context_string(self) -> str:
        """格式化为可注入 system prompt 的文本。"""
        parts: List[str] = []

        if self.memory_md_excerpt:
            parts.append("## 核心记忆 (MEMORY.md)")
            parts.append(self.memory_md_excerpt)

        if self.short_term:
            parts.append("\n## 近期会话记忆")
            for s in self.short_term:
                parts.append(f"- [{s.session_id}] {s.summary}")

        if self.long_term:
            parts.append("\n## 长期经验")
            for e in self.long_term:
                parts.append(f"- [{e.category}] {e.content}")

        if self.content:
            parts.append("\n## 相关内容记忆")
            for path, snippet in self.content:
                parts.append(f"- {path}: {snippet[:150]}")

        return "\n".join(parts) if parts else ""


_FORCE_RECALL_PATTERNS = [
    re.compile(r"(上次|之前|以前|过去|历史|之前我们|上回)", re.IGNORECASE),
    re.compile(r"(记得|还记得|你还记得)", re.IGNORECASE),
    re.compile(r"(经验|教训|惯例|偏好|习惯)", re.IGNORECASE),
    re.compile(r"(延续|继续|接着|根据上次)", re.IGNORECASE),
    re.compile(r"(笔记|文档|讲义|会议记录)", re.IGNORECASE),
]


class RecallPolicy:
    """记忆检索策略管理器。"""

    def __init__(
        self,
        force_recall: bool = True,
        top_n: int = 5,
        score_threshold: float = 0.3,
    ):
        self._force_recall = force_recall
        self._top_n = top_n
        self._score_threshold = score_threshold

    def should_recall(self, user_input: str) -> bool:
        """判断是否需要执行记忆检索。"""
        if self._force_recall:
            return True
        return any(p.search(user_input) for p in _FORCE_RECALL_PATTERNS)

    def recall(
        self,
        query: str,
        short_term_memory=None,
        long_term_memory=None,
        content_memory=None,
    ) -> RecallResult:
        """
        执行多路记忆检索。

        Args:
            query: 用户输入
            short_term_memory: ShortTermMemory 实例
            long_term_memory: LongTermMemory 实例
            content_memory: ContentMemory 实例

        Returns:
            RecallResult 聚合结果
        """
        result = RecallResult()

        if short_term_memory:
            result.short_term = short_term_memory.search(query, self._top_n)

        if long_term_memory:
            result.long_term = long_term_memory.search(query, self._top_n)
            md_content = long_term_memory.read_memory_md()
            if md_content and len(md_content) > 50:
                result.memory_md_excerpt = self._excerpt_memory_md(md_content, query)

        if content_memory:
            hits = content_memory.search(query, self._top_n)
            result.content = [(str(p), s) for p, s in hits]
            qmd_hits = content_memory.search_qmd(query, self._top_n)
            for hit in qmd_hits:
                path = hit.get("path", hit.get("file", "unknown"))
                snippet = hit.get("snippet", hit.get("content", ""))[:300]
                result.content.append((str(path), snippet))

        return result

    @staticmethod
    def _excerpt_memory_md(full_text: str, query: str, max_len: int = 1000) -> str:
        """从 MEMORY.md 中提取与查询相关的段落，或返回截断版本。"""
        if len(full_text) <= max_len:
            return full_text

        query_words = query.lower().split()
        paragraphs = full_text.split("\n\n")
        scored: List[Tuple[float, str]] = []
        for para in paragraphs:
            score = sum(1 for w in query_words if w in para.lower())
            scored.append((score, para))
        scored.sort(key=lambda x: x[0], reverse=True)

        result_parts: List[str] = []
        total = 0
        for _, para in scored:
            if total + len(para) > max_len:
                break
            result_parts.append(para)
            total += len(para)

        return "\n\n".join(result_parts) if result_parts else full_text[:max_len]
