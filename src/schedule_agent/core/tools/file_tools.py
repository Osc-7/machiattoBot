"""
文件读写工具 - 提供 read_file, write_file, modify_file

读取受 allow_read 配置控制，写入和修改需要 allow_write/allow_modify 权限。
"""

from pathlib import Path
from typing import Awaitable, Callable, Optional

from .base import BaseTool, ToolDefinition, ToolParameter, ToolResult
from schedule_agent.config import Config, FileToolsConfig, get_config


class ReadFileTool(BaseTool):
    """
    读取文件工具

    读取指定文件的内容。路径必须位于配置的 base_dir 下。
    """

    def __init__(
        self,
        config: Optional[Config] = None,
        file_tools_config: Optional[FileToolsConfig] = None,
    ):
        """
        初始化读取文件工具。

        Args:
            config: 应用配置（可选，默认使用全局配置）
            file_tools_config: 文件工具配置（可选，从 config 中获取）
        """
        self._config = config or get_config()
        self._ft_config = file_tools_config or self._config.file_tools

    @property
    def name(self) -> str:
        return "read_file"

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="read_file",
            description="""读取指定文件的内容。

当用户想要：
- 查看某个文件的内容
- 读取笔记、文档、配置文件
- 了解文件中写了什么

工具会：
- 检查路径是否在允许的目录内
- 返回文件文本内容（ UTF-8 编码）
- 对二进制文件返回错误""",
            parameters=[
                ToolParameter(
                    name="path",
                    type="string",
                    description="文件路径（相对或绝对，必须在允许的 base_dir 下）",
                    required=True,
                ),
                ToolParameter(
                    name="encoding",
                    type="string",
                    description="文件编码，默认 utf-8",
                    required=False,
                    default="utf-8",
                ),
            ],
            examples=[
                {
                    "description": "读取项目中的 README 文件",
                    "params": {"path": "README.md"},
                },
                {
                    "description": "读取指定编码的文件",
                    "params": {"path": "data.txt", "encoding": "gbk"},
                },
            ],
            usage_notes=[
                "路径不能超出配置的 base_dir，否则会被拒绝",
                "只能读取文本文件，二进制文件会返回错误",
                "文件不存在时返回明确错误",
            ],
        )

    def _resolve_path(self, path: str) -> tuple[Optional[Path], Optional[str]]:
        """
        解析并验证路径是否在 base_dir 内。

        Returns:
            (resolved_path, error_message) - 成功时 error_message 为 None
        """
        base = Path(self._ft_config.base_dir).resolve()
        try:
            resolved = (base / path).resolve()
            if not str(resolved).startswith(str(base)):
                return None, f"路径 '{path}' 超出允许的目录范围"
            return resolved, None
        except (OSError, ValueError) as e:
            return None, f"无效路径: {e}"

    async def execute(self, **kwargs) -> ToolResult:
        path_str = kwargs.get("path")
        if not path_str:
            return ToolResult(
                success=False,
                error="MISSING_PATH",
                message="缺少必需参数: path",
            )

        if not self._ft_config.allow_read:
            return ToolResult(
                success=False,
                error="PERMISSION_DENIED",
                message="文件读取功能未启用，请在配置中设置 file_tools.allow_read: true",
            )

        resolved, err = self._resolve_path(path_str)
        if err:
            return ToolResult(success=False, error="INVALID_PATH", message=err)

        encoding = kwargs.get("encoding", "utf-8")

        try:
            content = resolved.read_text(encoding=encoding)
            return ToolResult(
                success=True,
                data={"path": str(resolved), "content": content},
                message=f"成功读取文件: {resolved.name}",
            )
        except FileNotFoundError:
            return ToolResult(
                success=False,
                error="FILE_NOT_FOUND",
                message=f"文件不存在: {path_str}",
            )
        except UnicodeDecodeError as e:
            return ToolResult(
                success=False,
                error="ENCODING_ERROR",
                message=f"无法以 {encoding} 编码读取文件，可能是二进制文件: {e}",
            )
        except OSError as e:
            return ToolResult(
                success=False,
                error="IO_ERROR",
                message=f"读取失败: {e}",
            )


class WriteFileTool(BaseTool):
    """
    写入文件工具

    创建新文件或覆盖已有文件。需要权限控制（配置或回调确认）。
    """

    def __init__(
        self,
        config: Optional[Config] = None,
        file_tools_config: Optional[FileToolsConfig] = None,
        permission_provider: Optional[
            Callable[[str, str, str], Awaitable[bool]]
        ] = None,
    ):
        self._config = config or get_config()
        self._ft_config = file_tools_config or self._config.file_tools
        self._permission_provider = permission_provider

    @property
    def name(self) -> str:
        return "write_file"

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="write_file",
            description="""创建新文件或覆盖已有文件。

当用户想要：
- 创建新文件并写入内容
- 保存笔记、配置、代码片段
- 覆盖现有文件

工具会：
- 检查写入权限（配置或用户确认）
- 检查路径是否在允许的目录内
- 创建或覆盖文件
- 若文件已存在会完全覆盖原内容""",
            parameters=[
                ToolParameter(
                    name="path",
                    type="string",
                    description="文件路径（相对或绝对，必须在允许的 base_dir 下）",
                    required=True,
                ),
                ToolParameter(
                    name="content",
                    type="string",
                    description="要写入的完整文本内容",
                    required=True,
                ),
                ToolParameter(
                    name="encoding",
                    type="string",
                    description="文件编码，默认 utf-8",
                    required=False,
                    default="utf-8",
                ),
            ],
            examples=[
                {
                    "description": "创建并写入新文件",
                    "params": {"path": "notes.txt", "content": "今日待办：1. 开会 2. 写报告"},
                },
            ],
            usage_notes=[
                "写入和覆盖需要配置允许：file_tools.allow_write: true",
                "路径不能超出配置的 base_dir",
                "会完全覆盖已存在的文件",
            ],
        )

    def _resolve_path(self, path: str) -> tuple[Optional[Path], Optional[str]]:
        base = Path(self._ft_config.base_dir).resolve()
        try:
            resolved = (base / path).resolve()
            if not str(resolved).startswith(str(base)):
                return None, f"路径 '{path}' 超出允许的目录范围"
            return resolved, None
        except (OSError, ValueError) as e:
            return None, f"无效路径: {e}"

    async def execute(self, **kwargs) -> ToolResult:
        path_str = kwargs.get("path")
        content = kwargs.get("content")
        if not path_str:
            return ToolResult(
                success=False,
                error="MISSING_PATH",
                message="缺少必需参数: path",
            )
        if content is None:
            return ToolResult(
                success=False,
                error="MISSING_CONTENT",
                message="缺少必需参数: content",
            )

        if not self._ft_config.allow_write:
            return ToolResult(
                success=False,
                error="PERMISSION_DENIED",
                message="文件写入功能未启用。请在配置中设置 file_tools.allow_write: true",
            )

        resolved, err = self._resolve_path(path_str)
        if err:
            return ToolResult(success=False, error="INVALID_PATH", message=err)

        # 若有权限提供者，则调用确认
        if self._permission_provider:
            summary = f"写入 {path_str}，共 {len(content)} 字符"
            allowed = await self._permission_provider("write", path_str, summary)
            if not allowed:
                return ToolResult(
                    success=False,
                    error="USER_DENIED",
                    message="用户拒绝了写入操作",
                )

        encoding = kwargs.get("encoding", "utf-8")

        try:
            resolved.parent.mkdir(parents=True, exist_ok=True)
            resolved.write_text(content, encoding=encoding)
            return ToolResult(
                success=True,
                data={"path": str(resolved)},
                message=f"成功写入文件: {resolved.name}",
            )
        except OSError as e:
            return ToolResult(
                success=False,
                error="IO_ERROR",
                message=f"写入失败: {e}",
            )


class ModifyFileTool(BaseTool):
    """
    修改文件工具

    在现有文件中追加内容或替换部分内容。需要权限控制。
    """

    def __init__(
        self,
        config: Optional[Config] = None,
        file_tools_config: Optional[FileToolsConfig] = None,
        permission_provider: Optional[
            Callable[[str, str, str], Awaitable[bool]]
        ] = None,
    ):
        self._config = config or get_config()
        self._ft_config = file_tools_config or self._config.file_tools
        self._permission_provider = permission_provider

    @property
    def name(self) -> str:
        return "modify_file"

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="modify_file",
            description="""修改现有文件：追加内容或替换全部内容。

当用户想要：
- 在文件末尾追加内容
- 修改现有文件的内容
- 更新配置、笔记等

支持两种模式：
- append: 在文件末尾追加内容
- overwrite: 覆盖整个文件（与 write_file 类似，但语义为「修改」）""",
            parameters=[
                ToolParameter(
                    name="path",
                    type="string",
                    description="文件路径（相对或绝对，必须在允许的 base_dir 下）",
                    required=True,
                ),
                ToolParameter(
                    name="content",
                    type="string",
                    description="要追加或写入的内容",
                    required=True,
                ),
                ToolParameter(
                    name="mode",
                    type="string",
                    description="修改模式：append（追加）或 overwrite（覆盖）",
                    required=False,
                    enum=["append", "overwrite"],
                    default="append",
                ),
                ToolParameter(
                    name="encoding",
                    type="string",
                    description="文件编码，默认 utf-8",
                    required=False,
                    default="utf-8",
                ),
            ],
            examples=[
                {
                    "description": "在文件末尾追加内容",
                    "params": {
                        "path": "notes.txt",
                        "content": "\n追加一行",
                        "mode": "append",
                    },
                },
                {
                    "description": "覆盖整个文件",
                    "params": {"path": "config.txt", "content": "新配置", "mode": "overwrite"},
                },
            ],
            usage_notes=[
                "修改需要配置允许：file_tools.allow_modify: true",
                "路径不能超出配置的 base_dir",
                "append 模式下文件不存在会先创建",
            ],
        )

    def _resolve_path(self, path: str) -> tuple[Optional[Path], Optional[str]]:
        base = Path(self._ft_config.base_dir).resolve()
        try:
            resolved = (base / path).resolve()
            if not str(resolved).startswith(str(base)):
                return None, f"路径 '{path}' 超出允许的目录范围"
            return resolved, None
        except (OSError, ValueError) as e:
            return None, f"无效路径: {e}"

    async def execute(self, **kwargs) -> ToolResult:
        path_str = kwargs.get("path")
        content = kwargs.get("content")
        if not path_str:
            return ToolResult(
                success=False,
                error="MISSING_PATH",
                message="缺少必需参数: path",
            )
        if content is None:
            return ToolResult(
                success=False,
                error="MISSING_CONTENT",
                message="缺少必需参数: content",
            )

        if not self._ft_config.allow_modify:
            return ToolResult(
                success=False,
                error="PERMISSION_DENIED",
                message="文件修改功能未启用。请在配置中设置 file_tools.allow_modify: true",
            )

        resolved, err = self._resolve_path(path_str)
        if err:
            return ToolResult(success=False, error="INVALID_PATH", message=err)

        mode = kwargs.get("mode", "append")
        if mode not in ("append", "overwrite"):
            return ToolResult(
                success=False,
                error="INVALID_MODE",
                message="mode 必须为 append 或 overwrite",
            )

        action_cn = "追加" if mode == "append" else "覆盖"
        if self._permission_provider:
            summary = f"{action_cn} {path_str}，共 {len(content)} 字符"
            allowed = await self._permission_provider("modify", path_str, summary)
            if not allowed:
                return ToolResult(
                    success=False,
                    error="USER_DENIED",
                    message="用户拒绝了修改操作",
                )

        encoding = kwargs.get("encoding", "utf-8")

        try:
            resolved.parent.mkdir(parents=True, exist_ok=True)
            if mode == "append":
                with open(resolved, "a", encoding=encoding) as f:
                    f.write(content)
            else:
                resolved.write_text(content, encoding=encoding)
            return ToolResult(
                success=True,
                data={"path": str(resolved), "mode": mode},
                message=f"成功{action_cn}文件: {resolved.name}",
            )
        except OSError as e:
            return ToolResult(
                success=False,
                error="IO_ERROR",
                message=f"修改失败: {e}",
            )
