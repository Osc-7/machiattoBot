"""
工具注册表

管理所有可用工具的注册和执行。
"""

from typing import Any, Dict, List, Optional

from .base import BaseTool, ToolDefinition, ToolResult


class ToolRegistry:
    """
    工具注册表。

    管理所有可用工具的注册、查询和执行。
    """

    def __init__(self):
        """初始化工具注册表"""
        self._tools: Dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        """
        注册工具。

        Args:
            tool: 工具实例

        Raises:
            ValueError: 工具名称已存在
        """
        if tool.name in self._tools:
            raise ValueError(f"工具 '{tool.name}' 已注册")
        self._tools[tool.name] = tool

    def unregister(self, name: str) -> bool:
        """
        注销工具。

        Args:
            name: 工具名称

        Returns:
            是否成功注销
        """
        if name in self._tools:
            del self._tools[name]
            return True
        return False

    def get(self, name: str) -> Optional[BaseTool]:
        """
        获取工具。

        Args:
            name: 工具名称

        Returns:
            工具实例，如果不存在返回 None
        """
        return self._tools.get(name)

    def get_definition(self, name: str) -> Optional[ToolDefinition]:
        """
        获取工具定义。

        Args:
            name: 工具名称

        Returns:
            工具定义，如果不存在返回 None
        """
        tool = self.get(name)
        return tool.get_definition() if tool else None

    def get_all_definitions(self) -> List[Dict[str, Any]]:
        """
        获取所有工具的 OpenAI Function Calling 定义。

        Returns:
            工具定义列表
        """
        return [tool.to_openai_tool() for tool in self._tools.values()]

    def get_all_tools(self) -> List[BaseTool]:
        """
        获取所有已注册的工具。

        Returns:
            工具列表
        """
        return list(self._tools.values())

    async def execute(self, name: str, **kwargs) -> ToolResult:
        """
        执行工具。

        Args:
            name: 工具名称
            **kwargs: 工具参数

        Returns:
            工具执行结果

        Raises:
            ValueError: 工具不存在
        """
        tool = self.get(name)
        if tool is None:
            return ToolResult(
                success=False,
                error="TOOL_NOT_FOUND",
                message=f"工具 '{name}' 不存在",
            )
        return await tool.execute(**kwargs)

    def has(self, name: str) -> bool:
        """
        检查工具是否已注册。

        Args:
            name: 工具名称

        Returns:
            是否已注册
        """
        return name in self._tools

    def list_names(self) -> List[str]:
        """
        列出所有工具名称。

        Returns:
            工具名称列表
        """
        return list(self._tools.keys())

    def __len__(self) -> int:
        """返回已注册工具数量"""
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        """检查工具是否已注册"""
        return name in self._tools
