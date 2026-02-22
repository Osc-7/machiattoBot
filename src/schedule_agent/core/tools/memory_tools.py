"""
记忆系统工具集

为 Agent 提供记忆检索与写入能力：
- memory_search: 多路检索记忆（短期+长期+内容）
- memory_store: 将文本写入内容记忆
- memory_ingest: 将文件转为 Markdown 存入内容记忆
"""

from __future__ import annotations

from typing import Optional

from schedule_agent.config import Config, get_config
from schedule_agent.core.memory import (
    ContentMemory,
    LongTermMemory,
    RecallPolicy,
    ShortTermMemory,
)

from .base import BaseTool, ToolDefinition, ToolParameter, ToolResult


class MemorySearchTool(BaseTool):
    """多路记忆检索工具。"""

    def __init__(
        self,
        recall_policy: RecallPolicy,
        short_term: Optional[ShortTermMemory] = None,
        long_term: Optional[LongTermMemory] = None,
        content: Optional[ContentMemory] = None,
    ):
        self._recall = recall_policy
        self._short_term = short_term
        self._long_term = long_term
        self._content = content

    @property
    def name(self) -> str:
        return "memory_search"

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name,
            description="""在记忆系统中检索相关信息。

当需要：
- 回忆之前的对话内容、决策
- 查找用户偏好和习惯
- 检索笔记、文档、会议记录等内容
- 获取历史经验和教训

会同时检索短期记忆（最近会话）、长期记忆（提炼经验）、内容记忆（文档笔记）。""",
            parameters=[
                ToolParameter(
                    name="query",
                    type="string",
                    description="检索查询（自然语言）",
                    required=True,
                ),
                ToolParameter(
                    name="scope",
                    type="string",
                    description="检索范围: all(全部) | short_term(近期会话) | long_term(长期经验) | content(文档内容)",
                    required=False,
                    default="all",
                    enum=["all", "short_term", "long_term", "content"],
                ),
            ],
            examples=[
                {
                    "description": "搜索之前关于日程安排的讨论",
                    "params": {"query": "日程安排策略"},
                },
                {
                    "description": "只在文档中搜索 API 相关内容",
                    "params": {"query": "API 认证", "scope": "content"},
                },
            ],
            usage_notes=[
                "默认会同时搜索所有记忆层，通过 scope 可以限定范围",
                "返回结果包含来源标记，方便追溯",
            ],
        )

    async def execute(self, **kwargs) -> ToolResult:
        query = str(kwargs.get("query", "")).strip()
        if not query:
            return ToolResult(
                success=False,
                error="MISSING_QUERY",
                message="请提供检索查询内容",
            )

        scope = kwargs.get("scope", "all")

        st = self._short_term if scope in ("all", "short_term") else None
        lt = self._long_term if scope in ("all", "long_term") else None
        ct = self._content if scope in ("all", "content") else None

        result = self._recall.recall(
            query=query,
            short_term_memory=st,
            long_term_memory=lt,
            content_memory=ct,
        )

        if result.is_empty():
            return ToolResult(
                success=True,
                data={"results": []},
                message="未找到相关记忆",
            )

        data = {"results": []}
        if result.short_term:
            for s in result.short_term:
                data["results"].append({
                    "source": "short_term",
                    "session_id": s.session_id,
                    "summary": s.summary,
                    "time": s.time_start,
                })
        if result.long_term:
            for e in result.long_term:
                data["results"].append({
                    "source": "long_term",
                    "category": e.category,
                    "content": e.content,
                })
        if result.content:
            for path, snippet in result.content:
                data["results"].append({
                    "source": "content",
                    "path": path,
                    "snippet": snippet[:300],
                })
        if result.memory_md_excerpt:
            data["memory_md"] = result.memory_md_excerpt[:500]

        return ToolResult(
            success=True,
            data=data,
            message=f"找到 {len(data['results'])} 条相关记忆",
        )


class MemoryStoreTool(BaseTool):
    """将文本内容写入内容记忆。"""

    def __init__(self, content_memory: ContentMemory):
        self._content = content_memory

    @property
    def name(self) -> str:
        return "memory_store"

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name,
            description="""将文本内容写入内容记忆库。

当用户要求保存笔记、总结、经验教训时使用。内容会以 Markdown 格式持久化。""",
            parameters=[
                ToolParameter(
                    name="content",
                    type="string",
                    description="要保存的文本内容（Markdown 格式）",
                    required=True,
                ),
                ToolParameter(
                    name="filename",
                    type="string",
                    description="文件名（不含 .md 后缀）",
                    required=True,
                ),
                ToolParameter(
                    name="category",
                    type="string",
                    description="分类: docs | meeting | diary | lessons | notes | code | other",
                    required=False,
                    default="notes",
                    enum=["docs", "meeting", "diary", "lessons", "notes", "code", "other"],
                ),
            ],
            examples=[
                {
                    "description": "保存会议记录",
                    "params": {
                        "content": "# 周会记录\n\n讨论了 Q1 目标...",
                        "filename": "weekly-meeting-0222",
                        "category": "meeting",
                    },
                },
            ],
            usage_notes=[
                "content 建议使用 Markdown 格式",
                "文件存储在内容记忆库对应分类目录下",
            ],
        )

    async def execute(self, **kwargs) -> ToolResult:
        content = str(kwargs.get("content", "")).strip()
        filename = str(kwargs.get("filename", "")).strip()
        if not content or not filename:
            return ToolResult(
                success=False,
                error="MISSING_PARAMS",
                message="content 和 filename 均为必填",
            )

        category = kwargs.get("category", "notes")
        path = self._content.ingest_text(content, filename, category)

        return ToolResult(
            success=True,
            data={"path": str(path)},
            message=f"已保存到内容记忆: {path}",
        )


class MemoryIngestTool(BaseTool):
    """将文件转为 Markdown 存入内容记忆。"""

    def __init__(self, content_memory: ContentMemory):
        self._content = content_memory

    @property
    def name(self) -> str:
        return "memory_ingest"

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name,
            description="""将文件（PDF、Word 等）转为 Markdown 并存入内容记忆库。

依赖 markitdown 进行格式转换，支持 PDF、DOCX、HTML、PPTX 等格式。""",
            parameters=[
                ToolParameter(
                    name="file_path",
                    type="string",
                    description="源文件路径",
                    required=True,
                ),
                ToolParameter(
                    name="category",
                    type="string",
                    description="分类: docs | meeting | diary | lessons | notes | code | other",
                    required=False,
                    default="docs",
                    enum=["docs", "meeting", "diary", "lessons", "notes", "code", "other"],
                ),
                ToolParameter(
                    name="title",
                    type="string",
                    description="自定义标题（默认使用文件名）",
                    required=False,
                ),
            ],
            examples=[
                {
                    "description": "导入 PDF 讲义",
                    "params": {
                        "file_path": "/path/to/lecture.pdf",
                        "category": "docs",
                        "title": "机器学习讲义",
                    },
                },
            ],
            usage_notes=[
                "需要安装 markitdown（pip install markitdown）",
                "转换后的 Markdown 存储在内容记忆库对应分类目录下",
            ],
        )

    async def execute(self, **kwargs) -> ToolResult:
        file_path = str(kwargs.get("file_path", "")).strip()
        if not file_path:
            return ToolResult(
                success=False,
                error="MISSING_FILE_PATH",
                message="请提供文件路径",
            )

        category = kwargs.get("category", "docs")
        title = kwargs.get("title")

        result_path = self._content.ingest_file(file_path, category, title)
        if result_path is None:
            return ToolResult(
                success=False,
                error="INGEST_FAILED",
                message=f"文件转换失败: {file_path}（文件不存在或格式不支持）",
            )

        return ToolResult(
            success=True,
            data={"path": str(result_path)},
            message=f"已导入到内容记忆: {result_path}",
        )
