"""
网页搜索工具（Tavily MCP 适配）。

通过 MCP 代理的 Tavily search 工具按关键词搜索网络信息。
"""

from typing import Optional

from .base import BaseTool, ToolDefinition, ToolParameter, ToolResult
from .versioned_registry import VersionedToolRegistry


class WebSearchTool(BaseTool):
    """
    独立的联网搜索工具。

    工具只返回 Tavily 的结构化搜索结果，不在工具内部做二次 LLM 汇总。
    """

    def __init__(self, registry: VersionedToolRegistry):
        self._registry = registry

    @property
    def name(self) -> str:
        return "web_search"

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="web_search",
            description="""按关键词搜索网络公开信息并返回结构化结果。

当用户想要：
- 查询最新新闻、公告、技术动态
- 查找某个主题的资料来源链接
- 获取实时公开事实（天气、价格、政策更新等）

工具会自动：
- 调用 Tavily search 进行网络搜索
- 返回结构化结果（标题、链接、摘要等）

注意：此工具返回原始搜索结果，不在工具内做总结。""",
            parameters=[
                ToolParameter(
                    name="query",
                    type="string",
                    description="搜索关键词或问题描述",
                    required=True,
                ),
                ToolParameter(
                    name="max_results",
                    type="integer",
                    description="可选，返回结果数量上限",
                    required=False,
                ),
                ToolParameter(
                    name="search_depth",
                    type="string",
                    description="可选，搜索深度（如 basic/advanced）",
                    required=False,
                ),
                ToolParameter(
                    name="include_domains",
                    type="array",
                    description="可选，仅从指定域名搜索（字符串数组）",
                    required=False,
                ),
            ],
            usage_notes=[
                "结果为 Tavily 结构化搜索数据，后续回答由主对话 LLM基于 tool_result 组织",
                "若需要读取某个具体网页正文，优先使用 extract_web_content(url=...)",
            ],
            tags=["网络", "搜索"],
        )

    def _resolve_remote_tool_name(self) -> Optional[str]:
        names = self._registry.list_names()
        candidates = ["tavily-search", "search", "tavily_search"]
        for full_name in names:
            if full_name in candidates:
                return full_name
            for candidate in candidates:
                if full_name.endswith(f".{candidate}"):
                    return full_name
        return None

    async def execute(self, **kwargs) -> ToolResult:
        query = kwargs.get("query")
        max_results = kwargs.get("max_results")
        search_depth = kwargs.get("search_depth")
        include_domains = kwargs.get("include_domains")

        if not query:
            return ToolResult(
                success=False,
                error="MISSING_QUERY",
                message="缺少必需的参数：query",
            )

        remote_name = self._resolve_remote_tool_name()
        if not remote_name:
            return ToolResult(
                success=False,
                error="TAVILY_SEARCH_NOT_AVAILABLE",
                message="未找到 Tavily search 工具，请检查 MCP 配置与连接状态",
            )

        payload = {"query": query}
        if max_results is not None:
            payload["max_results"] = max_results
        if search_depth:
            payload["search_depth"] = search_depth
        if include_domains:
            payload["include_domains"] = include_domains

        result = await self._registry.execute(remote_name, **payload)
        if result.success:
            return ToolResult(
                success=True,
                data={"query": query, "search_result": result.data},
                message=f"搜索成功：{query}",
                metadata={"source_tool": remote_name},
            )

        return ToolResult(
            success=False,
            error=result.error,
            message=result.message or "网页搜索失败",
            metadata={"source_tool": remote_name},
        )
