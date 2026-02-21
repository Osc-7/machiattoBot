"""
MCP 客户端管理器。

管理多个 MCP Server 连接，并提供远程工具调用能力。
"""

from __future__ import annotations

import asyncio
import json
from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from schedule_agent.config import MCPConfig, MCPServerConfig
from schedule_agent.core.tools.base import ToolResult

from .proxy_tool import MCPProxyTool


@dataclass
class _ServerRuntime:
    """单个 MCP Server 的运行时信息。"""

    config: MCPServerConfig
    session: Any


class MCPClientManager:
    """MCP 客户端连接与工具调用管理。"""

    def __init__(self, config: MCPConfig):
        self._config = config
        self._exit_stack = AsyncExitStack()
        self._servers: Dict[str, _ServerRuntime] = {}
        self._proxy_tools: List[MCPProxyTool] = []
        self._connected = False

    async def connect(self) -> None:
        """连接所有启用的 MCP Server，并构建代理工具。"""
        if self._connected:
            return

        # 延迟导入，避免未安装 mcp SDK 时影响非 MCP 场景。
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
        except ImportError as e:
            raise RuntimeError(
                "未安装 mcp 依赖，请先执行: pip install -r requirements.txt"
            ) from e

        for server in self._config.servers:
            if not server.enabled:
                continue
            if server.transport != "stdio":
                continue

            server_params = StdioServerParameters(
                command=server.command,
                args=server.args,
                env=server.env or None,
                cwd=server.cwd,
            )

            read_stream, write_stream = await self._exit_stack.enter_async_context(
                stdio_client(server_params)
            )
            session = await self._exit_stack.enter_async_context(
                ClientSession(read_stream, write_stream)
            )

            await asyncio.wait_for(
                session.initialize(),
                timeout=server.init_timeout_seconds,
            )

            self._servers[server.name] = _ServerRuntime(config=server, session=session)

            tool_resp = await asyncio.wait_for(
                session.list_tools(),
                timeout=server.init_timeout_seconds,
            )
            tools = getattr(tool_resp, "tools", []) or []
            for tool in tools:
                remote_name = getattr(tool, "name", "")
                if not remote_name:
                    continue
                local_prefix = server.tool_name_prefix or server.name
                local_name = f"{local_prefix}.{remote_name}"
                if any(t.name == local_name for t in self._proxy_tools):
                    raise ValueError(f"MCP 工具名冲突: {local_name}")

                self._proxy_tools.append(
                    MCPProxyTool(
                        manager=self,
                        local_name=local_name,
                        server_name=server.name,
                        remote_name=remote_name,
                        description=getattr(tool, "description", "") or "MCP 远程工具",
                        input_schema=getattr(tool, "inputSchema", None)
                        or getattr(tool, "input_schema", None)
                        or {"type": "object", "properties": {}},
                    )
                )

        self._connected = True

    def get_proxy_tools(self) -> List[MCPProxyTool]:
        """获取已构建的 MCP 代理工具列表。"""
        return list(self._proxy_tools)

    async def call_tool(
        self,
        server_name: str,
        remote_tool_name: str,
        arguments: Dict[str, Any],
    ) -> ToolResult:
        """调用指定 MCP Server 的远程工具。"""
        runtime = self._servers.get(server_name)
        if runtime is None:
            return ToolResult(
                success=False,
                error="MCP_SERVER_NOT_FOUND",
                message=f"MCP Server 不存在或未连接: {server_name}",
            )

        timeout_seconds = runtime.config.call_timeout_seconds or self._config.call_timeout_seconds
        try:
            result = await asyncio.wait_for(
                runtime.session.call_tool(remote_tool_name, arguments=arguments),
                timeout=timeout_seconds,
            )
            return self._convert_call_result(result)
        except asyncio.TimeoutError:
            return ToolResult(
                success=False,
                error="MCP_TOOL_TIMEOUT",
                message=f"MCP 工具调用超时: {server_name}.{remote_tool_name}",
                metadata={"timeout_seconds": timeout_seconds},
            )
        except Exception as e:
            return ToolResult(
                success=False,
                error="MCP_TOOL_CALL_FAILED",
                message=f"MCP 工具调用失败: {server_name}.{remote_tool_name}: {str(e)}",
            )

    async def close(self) -> None:
        """关闭所有 MCP 连接。"""
        if not self._connected:
            return
        await self._exit_stack.aclose()
        self._servers.clear()
        self._proxy_tools.clear()
        self._connected = False

    def _convert_call_result(self, call_result: Any) -> ToolResult:
        """将 MCP 工具调用结果转换为本地 ToolResult。"""
        is_error = bool(
            getattr(call_result, "isError", False)
            or getattr(call_result, "is_error", False)
        )
        content = getattr(call_result, "content", None)
        structured = (
            getattr(call_result, "structuredContent", None)
            or getattr(call_result, "structured_content", None)
        )

        text_parts: List[str] = []
        serialized_content = []
        if isinstance(content, list):
            for block in content:
                serialized = self._serialize(block)
                serialized_content.append(serialized)
                if isinstance(serialized, dict) and "text" in serialized:
                    text_parts.append(str(serialized.get("text", "")))
                elif isinstance(serialized, str):
                    text_parts.append(serialized)

        data: Any = structured if structured is not None else serialized_content
        message = "\n".join([t for t in text_parts if t]).strip()
        if not message:
            message = "MCP 工具执行失败" if is_error else "MCP 工具执行成功"

        return ToolResult(
            success=not is_error,
            data=data,
            message=message,
            error="MCP_TOOL_ERROR" if is_error else None,
        )

    def _serialize(self, obj: Any) -> Any:
        """尽量将对象转换为可 JSON 序列化结构。"""
        if obj is None:
            return None
        if isinstance(obj, (str, int, float, bool, list, dict)):
            return obj
        if hasattr(obj, "model_dump"):
            return obj.model_dump()
        if hasattr(obj, "dict"):
            return obj.dict()
        try:
            return json.loads(json.dumps(obj, default=str))
        except Exception:
            return str(obj)
