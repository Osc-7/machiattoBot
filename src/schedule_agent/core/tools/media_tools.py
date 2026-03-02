"""
媒体挂载工具：将本地图片/视频标记为下一轮对话的多模态输入。

工具本身**不直接调用多模态模型**，仅负责：
- 接收本地媒体路径（通常位于 user_file/ 目录）
- 做基础参数校验
- 在 ToolResult.metadata 中声明 embed_in_next_call 标志和路径

ScheduleAgent 的 runtime 会在**下一次 LLM 调用前**：
- 读取这些路径指向的文件
- 将其转换为 OpenAI 兼容的多模态 content item（image_url / video_url）
- 以新的 user 消息形式附加到 messages 末尾
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .base import BaseTool, ToolDefinition, ToolParameter, ToolResult


@dataclass
class _AttachMediaParams:
    paths: List[str]

    @classmethod
    def from_kwargs(cls, **kwargs: Any) -> " _AttachMediaParams":
        path = kwargs.get("path")
        paths = kwargs.get("paths")

        collected: List[str] = []
        if isinstance(path, str) and path.strip():
            collected.append(path.strip())
        if isinstance(paths, list):
            for item in paths:
                if isinstance(item, str) and item.strip():
                    collected.append(item.strip())

        return cls(paths=collected)


class AttachMediaTool(BaseTool):
    """
    将本地图片/视频挂载到下一轮 LLM 调用的多模态消息中。

    注意：本工具**不直接进行识图/视频理解**，而是声明「下一轮请求需要附带这些媒体」。
    实际的多模态理解发生在下一次 chat_with_tools 调用中，由当前主模型统一处理文字+图像/视频。
    """

    @property
    def name(self) -> str:
        return "attach_media"

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="attach_media",
            description="""将本地图片/视频挂载为下一轮对话的多模态输入。

当你在推理中发现「需要查看某张截图/某个视频片段」时，使用本工具：
- 提供位于工作区（通常是 user_file/ 目录）中的媒体路径
- 工具不会直接调用多模态模型，只会在 metadata 中声明挂载请求
- ScheduleAgent 的运行时会在**下一轮 LLM 调用前**自动把这些媒体嵌入到 messages 里

推荐用法：
- 用户或其他工具先将文件保存到 user_file/ 目录
- 你调用 attach_media(path=\"user_file/xxx.png\") 或 attach_media(paths=[...])
- 下一轮回答时，直接根据「刚刚挂载的截图」继续推理，无需再关心 base64 或 URL 细节。
""",
            parameters=[
                ToolParameter(
                    name="path",
                    type="string",
                    description="单个媒体路径（优先使用相对 user_file/ 的路径，也可为绝对路径）",
                    required=False,
                ),
                ToolParameter(
                    name="paths",
                    type="array",
                    description="多个媒体路径列表，与 path 二选一；两者同时提供时会合并去重。",
                    required=False,
                ),
            ],
            examples=[
                {
                    "description": "挂载一张错误截图，供下一轮分析",
                    "params": {"path": "user_file/error_screenshot.png"},
                },
                {
                    "description": "一次挂载多页 PDF 截图",
                    "params": {
                        "paths": [
                            "user_file/page_1.png",
                            "user_file/page_2.png",
                        ]
                    },
                },
            ],
            usage_notes=[
                "本工具不会直接返回图片内容或进行识图，只是声明下一轮需要附带的媒体。",
                "路径推荐使用 user_file/ 前缀下的相对路径，方便与上传逻辑对齐。",
                "调用成功后，你可以在后续回复中自然地引用这些媒体，例如：“根据刚才挂载的截图……”。",
            ],
            tags=["多模态", "媒体", "挂载"],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        params = _AttachMediaParams.from_kwargs(**kwargs)
        if not params.paths:
            return ToolResult(
                success=False,
                error="MISSING_MEDIA_PATH",
                message="必须提供 path 或 paths 中的至少一个媒体路径。",
            )

        # 不做实际文件读取，仅把路径交给 runtime，在下一轮调用前注入多模态内容。
        unique_paths = list(dict.fromkeys(params.paths))

        return ToolResult(
            success=True,
            data={"paths": unique_paths},
            message="媒体已标记，将在下一轮 LLM 调用中作为多模态输入附加。",
            metadata={"embed_in_next_call": True, "paths": unique_paths},
        )

