"""
MCP 远程工具代理。

将 MCP Server 暴露的工具包装为本地 BaseTool，复用现有 ToolRegistry 与 Agent 循环。
"""

from __future__ import annotations

from typing import Any, Dict, List

from agent_core.tools.base import BaseTool, ToolDefinition, ToolParameter, ToolResult


def _schema_to_parameters(input_schema: Dict[str, Any]) -> List[ToolParameter]:
    """将 MCP inputSchema 映射为本地 ToolParameter 列表。"""
    properties = input_schema.get("properties", {}) if isinstance(input_schema, dict) else {}
    required = set(input_schema.get("required", []) if isinstance(input_schema, dict) else [])

    params: List[ToolParameter] = []
    for name, schema in properties.items():
        if not isinstance(schema, dict):
            continue
        params.append(
            ToolParameter(
                name=name,
                type=schema.get("type", "string"),
                description=schema.get("description", ""),
                required=name in required,
                enum=schema.get("enum"),
                default=schema.get("default"),
            )
        )
    return params


class MCPProxyTool(BaseTool):
    """MCP 远程工具在本地的代理实现。"""

    def __init__(
        self,
        manager: Any,
        local_name: str,
        server_name: str,
        remote_name: str,
        description: str,
        input_schema: Dict[str, Any],
    ):
        self._manager = manager
        self._local_name = local_name
        self._server_name = server_name
        self._remote_name = remote_name
        self._description = description or "MCP 远程工具"
        self._input_schema = input_schema or {"type": "object", "properties": {}}

    @property
    def name(self) -> str:
        return self._local_name

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self._local_name,
            description=self._description,
            parameters=_schema_to_parameters(self._input_schema),
            usage_notes=[
                f"该工具来自 MCP Server: {self._server_name}",
                f"远程工具名: {self._remote_name}",
            ],
        )

    async def execute(self, **kwargs) -> ToolResult:
        return await self._manager.call_tool(
            server_name=self._server_name,
            remote_tool_name=self._remote_name,
            arguments=kwargs,
        )
