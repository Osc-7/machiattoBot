"""
工作记忆 - 会话内滑动窗口 + LLM 总结

在 ConversationContext 的基础上增加 token 估算与窗口总结能力：
- 每次 add_message 后估算总 token 数
- 接近阈值时触发 LLM 总结，将旧消息折叠为摘要块
- 保留最近 N 轮原始消息
"""

from __future__ import annotations

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

    def check_threshold(self) -> bool:
        """检查当前消息是否接近 token 阈值，更新 _needs_summarize。"""
        messages = self._context.get_messages()
        current_tokens = estimate_messages_tokens(messages)
        limit = int(self._max_tokens * self._threshold)
        self._needs_summarize = current_tokens >= limit
        return self._needs_summarize

    def get_current_tokens(self) -> int:
        return estimate_messages_tokens(self._context.get_messages())

    async def maybe_summarize(self, llm_client) -> bool:
        """
        若超过阈值，调用 LLM 对旧消息进行总结并折叠。

        Returns:
            是否执行了总结
        """
        if not self.check_threshold():
            return False

        messages = self._context.get_messages()
        if len(messages) <= self._keep_recent * 2:
            return False

        keep_count = self._keep_recent * 2
        old_messages = messages[:-keep_count]
        recent_messages = messages[-keep_count:]

        summary_input = self._format_messages_for_summary(old_messages)
        if self._running_summary:
            summary_input = f"之前的摘要：\n{self._running_summary}\n\n新增对话：\n{summary_input}"

        response = await llm_client.chat(
            messages=[{"role": "user", "content": summary_input}],
            system_message=_SUMMARIZE_SYSTEM_PROMPT,
        )

        self._running_summary = response.content or ""

        summary_message = {
            "role": "system",
            "content": f"[会话进行中摘要]\n{self._running_summary}",
        }

        self._context.messages.clear()
        self._context.messages.append(summary_message)
        self._context.messages.extend(recent_messages)

        self._needs_summarize = False
        return True

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
