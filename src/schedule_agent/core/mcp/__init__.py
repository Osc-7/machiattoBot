"""
MCP 客户端适配层。

负责连接 MCP Server，并将远端工具包装为本地 BaseTool。
"""

from .client import MCPClientManager
from .proxy_tool import MCPProxyTool

__all__ = [
    "MCPClientManager",
    "MCPProxyTool",
]
