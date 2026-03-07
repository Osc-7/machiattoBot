#!/usr/bin/env python3
"""诊断 MCP 连接：逐个尝试已启用的 MCP Server，并给出失败原因与修复建议。

用法（在项目根目录）:
  . init.sh   # 或 source init.sh
  python scripts/diagnose_mcp.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

# 确保项目根在 path 中
_root = Path(__file__).resolve().parents[1]
if str(_root / "src") not in sys.path:
    sys.path.insert(0, str(_root / "src"))


async def _try_one_server(server, timeout_seconds: int) -> tuple[bool, str]:
    """尝试连接单个 stdio MCP server，返回 (成功?, 消息)。"""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    merged_env = {**os.environ, **(server.env or {})}
    merged_env["NODE_NO_WARNINGS"] = "1"
    merged_env["NODE_ENV"] = "production"

    server_params = StdioServerParameters(
        command=server.command,
        args=server.args,
        env=merged_env,
        cwd=server.cwd or ".",
    )
    try:
        async with stdio_client(server_params, errlog=sys.stderr) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await asyncio.wait_for(session.initialize(), timeout=timeout_seconds)
                tool_resp = await asyncio.wait_for(
                    session.list_tools(),
                    timeout=timeout_seconds,
                )
                tools = getattr(tool_resp, "tools", []) or []
                return True, f"OK，共 {len(tools)} 个工具"
    except asyncio.TimeoutError:
        return False, f"超时（{timeout_seconds}s）"
    except FileNotFoundError as e:
        return False, f"命令不存在: {e}"
    except Exception as e:
        msg = f"{type(e).__name__}: {e}"
        # ExceptionGroup 可能嵌套，取首个叶子异常便于阅读
        if hasattr(e, "exceptions") and e.exceptions:
            leaf = e.exceptions[0]
            while hasattr(leaf, "exceptions") and leaf.exceptions:
                leaf = leaf.exceptions[0]
            msg += f" (原因: {type(leaf).__name__}: {leaf})"
        return False, msg


def main() -> None:
    from agent.config import get_config

    cfg = get_config()
    if not cfg.mcp.enabled:
        print("config.yaml 中 mcp.enabled 为 false，跳过诊断。")
        return
    servers = [s for s in cfg.mcp.servers if s.enabled and s.transport == "stdio"]
    if not servers:
        print("没有已启用的 stdio 类型 MCP server，跳过诊断。")
        return

    # 若启用了 Tavily 但未配置 API Key，提示
    tavily_enabled = any(s.name == "tavily" for s in servers)
    if tavily_enabled and not os.environ.get("TAVILY_API_KEY"):
        print("提示: Tavily 已启用但未设置 TAVILY_API_KEY，连接会失败。")
        print("  可执行: export TAVILY_API_KEY='your-key' 或在 .env 中配置。\n")

    print("逐个测试 MCP server（超时 15s）:\n")
    for server in servers:
        args_preview = " ".join(server.args)
        if len(args_preview) > 50:
            args_preview = args_preview[:47] + "..."
        print(f"  [{server.name}] {server.command} {args_preview}")
        ok, msg = asyncio.run(_try_one_server(server, timeout_seconds=15))
        if ok:
            print(f"    -> {msg}")
        else:
            print(f"    -> 失败: {msg}")
            if server.name == "tavily":
                if "超时" in msg:
                    print("      建议: 检查网络与 TAVILY_API_KEY，或暂时在 config 中将 tavily.enabled 设为 false。")
                elif "ExceptionGroup" in msg or "tavilyApiKey" in msg:
                    print("      建议: 未配置或无效的 TAVILY_API_KEY 会导致连接失败，请设置后重试或在 config 中将 tavily.enabled 设为 false。")
            if server.name == "schedule_tools":
                print("      建议: 确保在项目根目录执行，且 python 能执行 mcp_server.py。")
        print()
    print("诊断结束。")


if __name__ == "__main__":
    main()
