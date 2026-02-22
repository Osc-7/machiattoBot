"""
工作记忆 - 会话内滑动窗口 + LLM 总结

在 ConversationContext 的基础上增加 token 监控与窗口总结能力：
- 使用 LLM 调用的真实 prompt_tokens 判断阈值（由 Agent 传入），无则回退估算
- 接近阈值时触发 LLM 总结，与主对话并行执行，完成后合并
- 保留最近 N 轮原始消息
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List, Optional

from schedule_agent.core.context.conversation import ConversationContext

_SUMMARIZE_SYSTEM_PROMPT = """\
你是一个对话摘要引擎。给定一段多轮对话历史，请输出一段简洁而准确的摘要，保留：
- 用户的核心意图和需求
- 已做出的关键决策和结论
- 待解决的问题
- 涉及的具体时间、数据、文件名

不需要打招呼或解释，直接输出摘要。使用中文。"""

_SESSION_SUMMARIZE_SYSTEM_PROMPT = """\
你是一个会话总结引擎。给定一整个会话的对话历史（包含用户消息、助手消息、工具调用及结果），
请输出一个结构化的 JSON 对象：
{
  "summary": "会话内容的完整摘要（2-5 句话）",
  "decisions": ["本次会话做出的关键决策列表"],
  "open_questions": ["会话结束时仍未解决的问题"],
  "referenced_files": ["对话中涉及/提到的文件路径列表"],
  "tags": ["关键词标签列表"]
}

只输出合法 JSON，不要包含 markdown 代码块标记或其他文本。使用中文。"""


def estimate_tokens(text: str) -> int:
    """粗略估算文本的 token 数（中文约 1.5 字/token，英文约 4 字符/token）。"""
    if not text:
        return 0
    chinese_chars = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    other_chars = len(text) - chinese_chars
    return int(chinese_chars / 1.5 + other_chars / 4) + 1


def estimate_messages_tokens(messages: List[Dict[str, Any]]) -> int:
    """估算消息列表的总 token 数。"""
    total = 0
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            total += estimate_tokens(content)
        tool_calls = msg.get("tool_calls", [])
        if tool_calls:
            total += estimate_tokens(json.dumps(tool_calls, ensure_ascii=False))
        total += 4  # role/name overhead
    return total


class WorkingMemory:
    """
    工作记忆管理器。

    包装 ConversationContext，在其上叠加 token 监控和窗口总结。
    """

    def __init__(
        self,
        context: ConversationContext,
        max_tokens: int = 8000,
        threshold: float = 0.8,
        keep_recent: int = 4,
    ):
        self._context = context
        self._max_tokens = max_tokens
        self._threshold = threshold
        self._keep_recent = keep_recent
        self._running_summary: Optional[str] = None
        self._needs_summarize = False

    @property
    def context(self) -> ConversationContext:
        return self._context

    @property
    def running_summary(self) -> Optional[str]:
        """当前滑动窗口的累积摘要。"""
        return self._running_summary

    @property
    def needs_summarize(self) -> bool:
        """是否需要触发窗口总结。"""
        return self._needs_summarize

    def check_threshold(self, actual_tokens: Optional[int] = None) -> bool:
        """
        检查是否接近 token 阈值，更新 _needs_summarize。

        Args:
            actual_tokens: 上一轮 LLM 的 prompt_tokens（日志中有记录），若提供则优先使用
        """
        if actual_tokens is not None and actual_tokens > 0:
            current_tokens = actual_tokens
        else:
            current_tokens = estimate_messages_tokens(self._context.get_messages())
        limit = int(self._max_tokens * self._threshold)
        self._needs_summarize = current_tokens >= limit
        return self._needs_summarize

    def get_current_tokens(self, actual_tokens: Optional[int] = None) -> int:
        """获取当前 token 数，优先使用 actual_tokens。"""
        if actual_tokens is not None and actual_tokens > 0:
            return actual_tokens
        return estimate_messages_tokens(self._context.get_messages())

    def start_summarize(
        self, llm_client
    ) -> Optional[tuple[asyncio.Task[str], int]]:
        """
        若超过阈值，启动异步总结任务，与主 LLM 对话并行执行。

        Returns:
            (task, recent_start_index) 或 None。调用方需 await task 后在 apply_summary
        """
        messages = self._context.get_messages()
        if len(messages) <= self._keep_recent * 2:
            return None

        keep_count = self._keep_recent * 2
        recent_start = len(messages) - keep_count
        old_messages = messages[:recent_start]

        summary_input = self._format_messages_for_summary(old_messages)
        if self._running_summary:
            summary_input = f"之前的摘要：\n{self._running_summary}\n\n新增对话：\n{summary_input}"

        async def _do_summarize() -> str:
            response = await llm_client.chat(
                messages=[{"role": "user", "content": summary_input}],
                system_message=_SUMMARIZE_SYSTEM_PROMPT,
            )
            return response.content or ""

        task = asyncio.create_task(_do_summarize())
        return (task, recent_start)

    def apply_summary(self, summary_text: str, recent_start: int) -> None:
        """
        合并总结结果：将 summary 替换旧消息，保留 recent_start 及之后的上下文。
        应在主 LLM 流程结束后、await 总结 task 完成后调用。
        """
        self._running_summary = summary_text
        summary_message = {
            "role": "system",
            "content": f"[会话进行中摘要]\n{self._running_summary}",
        }
        messages = self._context.get_messages()
        self._context.messages.clear()
        self._context.messages.append(summary_message)
        self._context.messages.extend(messages[recent_start:])
        self._needs_summarize = False

    async def summarize_session(self, llm_client) -> Dict[str, Any]:
        """
        会话结束时总结整个对话，返回结构化摘要数据。

        Returns:
            包含 summary, decisions, open_questions, referenced_files, tags 的字典
        """
        messages = self._context.get_messages()
        if not messages:
            return {
                "summary": "空会话",
                "decisions": [],
                "open_questions": [],
                "referenced_files": [],
                "tags": [],
            }

        conversation_text = self._format_messages_for_summary(messages)
        if self._running_summary:
            conversation_text = (
                f"之前折叠的摘要：\n{self._running_summary}\n\n"
                f"最近对话：\n{conversation_text}"
            )

        response = await llm_client.chat(
            messages=[{"role": "user", "content": conversation_text}],
            system_message=_SESSION_SUMMARIZE_SYSTEM_PROMPT,
        )

        raw = (response.content or "").strip()
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

        try:
            result = json.loads(raw)
        except json.JSONDecodeError:
            result = {
                "summary": raw,
                "decisions": [],
                "open_questions": [],
                "referenced_files": [],
                "tags": [],
            }

        for key in ("summary", "decisions", "open_questions", "referenced_files", "tags"):
            result.setdefault(key, [] if key != "summary" else "")

        return result

    @staticmethod
    def _format_messages_for_summary(messages: List[Dict[str, Any]]) -> str:
        """将消息列表格式化为可读文本，供 LLM 总结。"""
        parts: List[str] = []
        for msg in messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")

            if role == "system" and "[会话进行中摘要]" in (content or ""):
                parts.append(f"[摘要] {content}")
                continue

            if role == "user":
                parts.append(f"用户: {content}")
            elif role == "assistant":
                if content:
                    parts.append(f"助手: {content}")
                tool_calls = msg.get("tool_calls", [])
                if tool_calls:
                    for tc in tool_calls:
                        fn = tc.get("function", {})
                        parts.append(f"助手调用工具: {fn.get('name', '?')}({fn.get('arguments', '')})")
            elif role == "tool":
                tc_id = msg.get("tool_call_id", "?")
                parts.append(f"工具结果[{tc_id}]: {content[:500]}")
            else:
                parts.append(f"[{role}] {content}")

        return "\n".join(parts)
