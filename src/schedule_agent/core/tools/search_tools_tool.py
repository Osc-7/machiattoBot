"""
工具搜索工具。

给 LLM 提供按需发现能力：先搜索，再调用。
"""

from __future__ import annotations

from typing import Any, List, TYPE_CHECKING

from .base import BaseTool, ToolDefinition, ToolParameter, ToolResult
from .versioned_registry import VersionedToolRegistry

if TYPE_CHECKING:
    from schedule_agent.core.orchestrator import ToolWorkingSetManager


class SearchToolsTool(BaseTool):
    """搜索工具库并更新工作集。"""

    def __init__(self, registry: VersionedToolRegistry, working_set: "ToolWorkingSetManager"):
        self._registry = registry
        self._working_set = working_set

    @property
    def name(self) -> str:
        return "search_tools"

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name,
            description=(
                "在完整工具库中搜索可用工具。当你需要当前看不到的能力时，"
                "先调用此工具查询，再使用 call_tool 执行。"
            ),
            parameters=[
                ToolParameter(
                    name="query",
                    type="string",
                    description="自然语言查询，例如：创建日程、查询任务、解析时间、读取文件",
                    required=True,
                ),
                ToolParameter(
                    name="limit",
                    type="integer",
                    description="返回数量上限，默认 8",
                    required=False,
                    default=8,
                ),
            ],
            usage_notes=[
                "搜索结果会被加入当前会话的工具工作集（LRU）。",
                "下一轮推理时，命中的工具可能直接出现在可见工具列表里。",
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        query = str(kwargs.get("query", "")).strip()
        if not query:
            return ToolResult(
                success=False,
                error="INVALID_ARGUMENTS",
                message="query 不能为空",
            )

        limit_raw = kwargs.get("limit", 8)
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            limit = 8
        limit = max(1, min(limit, 20))

        exclude_names: List[str] = [self.name]
        matches = self._registry.search(query=query, limit=limit, exclude_names=exclude_names)
        self._working_set.add_to_working_set([item["name"] for item in matches])

        return ToolResult(
            success=True,
            data={
                "query": query,
                "count": len(matches),
                "tools": matches,
            },
            message=f"已找到 {len(matches)} 个相关工具",
        )
