"""L2 tool_result 历史清扫单测。"""

from __future__ import annotations

import json

from agent_core.agent.tool_result_clearing import (
    apply_clearing_to_context,
    clear_stale_tool_results,
)
from agent_core.context.conversation import ConversationContext
from agent_core.memory.working_memory import estimate_messages_tokens, estimate_tokens


def _big(n_tokens: int = 5000) -> str:
    return ("abcdefghij" * 10) * (n_tokens // 25 + 1)


def _tool_msg(call_id: str, content: str) -> dict:
    return {"role": "tool", "tool_call_id": call_id, "content": content}


def _assistant_with_tools(*call_ids: str) -> dict:
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": cid,
                "type": "function",
                "function": {"name": "gpu_output", "arguments": "{}"},
            }
            for cid in call_ids
        ],
    }


class TestClearStaleToolResults:
    def test_keeps_recent_and_clears_older_large(self):
        messages = [
            {"role": "user", "content": "go"},
        ]
        for i in range(8):
            cid = f"call_{i}"
            messages.append(_assistant_with_tools(cid))
            messages.append(_tool_msg(cid, _big(5000)))

        before = estimate_messages_tokens(messages)
        _, outcome = clear_stale_tool_results(
            messages, keep_recent=3, min_tokens=2000
        )
        after = estimate_messages_tokens(messages)

        assert outcome.cleared == 5  # 8 - 3
        assert outcome.kept == 3
        assert after < before

        # 配对仍在：每条 assistant tool_calls 后仍有对应 tool 消息
        tool_ids = [
            m["tool_call_id"] for m in messages if m.get("role") == "tool"
        ]
        assert len(tool_ids) == 8
        assert all(isinstance(m.get("content"), str) for m in messages if m.get("role") == "tool")

        # 最早的被清扫
        first_tool = next(m for m in messages if m.get("tool_call_id") == "call_0")
        assert first_tool["content"].startswith("[cleared tool_result")
        # 最近 3 条仍是大内容
        for cid in ("call_5", "call_6", "call_7"):
            m = next(x for x in messages if x.get("tool_call_id") == cid)
            assert not m["content"].startswith("[cleared tool_result")

    def test_skips_small_results(self):
        messages = [
            _assistant_with_tools("a", "b"),
            _tool_msg("a", "tiny"),
            _tool_msg("b", _big(5000)),
            _assistant_with_tools("c"),
            _tool_msg("c", _big(5000)),
        ]
        _, outcome = clear_stale_tool_results(
            messages, keep_recent=1, min_tokens=2000
        )
        # a 太小跳过；b 被清；c 保留
        assert outcome.cleared == 1
        assert messages[1]["content"] == "tiny"
        assert messages[2]["content"].startswith("[cleared tool_result")
        assert not messages[4]["content"].startswith("[cleared tool_result")

    def test_preserves_overflow_path_in_placeholder(self):
        payload = {
            "success": True,
            "message": "truncated",
            "data": {
                "truncated": True,
                "overflow_path": ".tool_results/foo.json",
                "preview": _big(3000),
            },
        }
        content = json.dumps(payload, ensure_ascii=False)
        # 再垫大一点确保超 min_tokens
        content = content + _big(1000)
        messages = [
            _assistant_with_tools("old", "new"),
            _tool_msg("old", content),
            _tool_msg("new", "recent small"),
        ]
        clear_stale_tool_results(messages, keep_recent=1, min_tokens=500)
        assert ".tool_results/foo.json" in messages[1]["content"]

    def test_idempotent_on_already_cleared(self):
        messages = [
            _assistant_with_tools("x"),
            _tool_msg("x", "[cleared tool_result id=x; original~9999 tokens; re-call tool]"),
            _assistant_with_tools("y"),
            _tool_msg("y", _big(4000)),
        ]
        _, outcome = clear_stale_tool_results(
            messages, keep_recent=0, min_tokens=100
        )
        assert outcome.skipped_already_cleared == 1
        assert outcome.cleared == 1

    def test_apply_to_conversation_context(self):
        ctx = ConversationContext()
        ctx.messages = [
            {"role": "user", "content": "hi"},
            _assistant_with_tools("t1"),
            _tool_msg("t1", _big(6000)),
            _assistant_with_tools("t2"),
            _tool_msg("t2", _big(6000)),
        ]
        outcome = apply_clearing_to_context(ctx, keep_recent=1, min_tokens=1000)
        assert outcome.cleared == 1
        assert ctx.messages[2]["content"].startswith("[cleared tool_result")
        assert estimate_tokens(ctx.messages[2]["content"]) < 200


class TestScrubOversizedToolResults:
    def test_scrubs_even_recent_poison(self):
        """最近几条假截断巨石也必须被 scrub（L2 keep 保不住它们）。"""
        from agent_core.agent.tool_result_clearing import scrub_oversized_tool_results

        poison = _big(100_000)  # ~100k tokens
        messages = [
            {"role": "user", "content": "wake"},
            _assistant_with_tools("recent"),
            _tool_msg(
                "recent",
                json.dumps(
                    {
                        "success": True,
                        "message": poison,
                        "data": {
                            "truncated": True,
                            "overflow_path": ".tool_results/poison.json",
                            "preview": poison[:1000],
                        },
                    },
                    ensure_ascii=False,
                ),
            ),
        ]
        before = estimate_tokens(messages[2]["content"])
        assert before > 50_000
        _, outcome = scrub_oversized_tool_results(messages, max_tokens=15_000)
        assert outcome.scrubbed == 1
        assert messages[2]["content"].startswith("[scrubbed oversized tool_result")
        assert ".tool_results/poison.json" in messages[2]["content"]
        assert estimate_tokens(messages[2]["content"]) < 200

    def test_leaves_small_results(self):
        from agent_core.agent.tool_result_clearing import scrub_oversized_tool_results

        messages = [
            _assistant_with_tools("a"),
            _tool_msg("a", "tiny ok"),
        ]
        _, outcome = scrub_oversized_tool_results(messages, max_tokens=15_000)
        assert outcome.scrubbed == 0
        assert messages[1]["content"] == "tiny ok"


class TestContextOverflowHttpDetection:
    def test_detects_token_keywords(self):
        from agent_core.agent.agent import AgentCore
        import httpx

        agent = object.__new__(AgentCore)
        agent._estimate_current_context_tokens = lambda: 10  # type: ignore
        agent._compute_compress_threshold = lambda: 100_000  # type: ignore

        req = httpx.Request("POST", "https://example.com/v1/messages")
        resp = httpx.Response(
            400,
            request=req,
            text='{"error":{"message":"maximum context length exceeded"}}',
        )
        exc = httpx.HTTPStatusError("bad", request=req, response=resp)
        assert agent._is_context_overflow_http_error(exc) is True

    def test_empty_body_only_when_context_large(self):
        from agent_core.agent.agent import AgentCore
        import httpx

        agent = object.__new__(AgentCore)
        req = httpx.Request("POST", "https://example.com/v1/messages")
        resp = httpx.Response(400, request=req, text="")
        exc = httpx.HTTPStatusError("bad", request=req, response=resp)

        agent._estimate_current_context_tokens = lambda: 10  # type: ignore
        agent._compute_compress_threshold = lambda: 100_000  # type: ignore
        assert agent._is_context_overflow_http_error(exc) is False

        agent._estimate_current_context_tokens = lambda: 80_000  # type: ignore
        agent._compute_compress_threshold = lambda: 100_000  # type: ignore
        assert agent._is_context_overflow_http_error(exc) is True

    def test_nonempty_body_without_keywords_when_context_large(self):
        """高估算时：即便 body 无关键词也当 overflow（Kimi 怪文案）。"""
        from agent_core.agent.agent import AgentCore
        import httpx

        agent = object.__new__(AgentCore)
        agent._estimate_current_context_tokens = lambda: 900_000  # type: ignore
        agent._compute_compress_threshold = lambda: 200_000  # type: ignore
        req = httpx.Request("POST", "https://example.com/v1/messages")
        resp = httpx.Response(400, request=req, text='{"error":"bad request"}')
        exc = httpx.HTTPStatusError("bad", request=req, response=resp)
        assert agent._is_context_overflow_http_error(exc) is True

    def test_schema_400_not_treated_as_overflow(self):
        from agent_core.agent.agent import AgentCore
        import httpx

        agent = object.__new__(AgentCore)
        # 小上下文：schema 400 不应触发
        agent._estimate_current_context_tokens = lambda: 5_000  # type: ignore
        agent._compute_compress_threshold = lambda: 100_000  # type: ignore
        req = httpx.Request("POST", "https://example.com/v1/messages")
        resp = httpx.Response(
            400,
            request=req,
            text='{"error":{"message":"invalid tool schema: missing name"}}',
        )
        exc = httpx.HTTPStatusError("bad", request=req, response=resp)
        assert agent._is_context_overflow_http_error(exc) is False
