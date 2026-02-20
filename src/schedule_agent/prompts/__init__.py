"""
Prompt 管理模块

用于加载和组合各类系统提示、用户提示等。
支持三模式组装：full（主 Agent）、minimal（子 Agent）、none（仅身份）。
"""

from .loader import PromptMode, build_system_prompt

__all__ = ["build_system_prompt", "PromptMode"]
