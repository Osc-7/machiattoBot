"""
CLI 输出样式

在 TTY 下使用 ANSI 颜色与粗体提升可读性；非 TTY 或管道时回退为纯文本。
"""

import sys

# ANSI 代码（仅在 stdout 为 TTY 时启用）
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
# 前景色
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
MAGENTA = "\033[35m"
BLUE = "\033[34m"


def _use_color() -> bool:
    """是否使用颜色（仅交互式终端）"""
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


def t(text: str, color: str = "", bold: bool = False) -> str:
    """
    按当前环境返回带样式或纯文本。

    Args:
        text: 原始文本
        color: ANSI 颜色码（如 CYAN）
        bold: 是否加粗
    """
    if not _use_color():
        return text
    parts = []
    if bold:
        parts.append(BOLD)
    if color:
        parts.append(color)
    parts.append(text)
    parts.append(RESET)
    return "".join(parts)


def title(text: str) -> str:
    """区块标题（粗体 + 青色）"""
    return t(text, CYAN, bold=True)


def hint(text: str) -> str:
    """提示/说明（暗色）"""
    return t(text, DIM)


def label(text: str) -> str:
    """标签（绿色）"""
    return t(text, GREEN)


def accent(text: str) -> str:
    """强调（黄色）"""
    return t(text, YELLOW)


def prompt_prefix() -> str:
    """输入提示符「你: 」的样式"""
    return t("你: ", CYAN, bold=True)


def assistant_prefix() -> str:
    """助手回复前的标签样式"""
    return t("助手: ", GREEN, bold=True)


def sep_line(char: str = "-", length: int = 50) -> str:
    """分隔线"""
    return char * length
