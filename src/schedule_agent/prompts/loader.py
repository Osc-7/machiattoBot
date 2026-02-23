"""
Prompt 加载与组合

参考 [OpenClaw 系统提示词](https://docs.openclaw.ai/zh-CN/concepts/system-prompt) 架构：
- 设计紧凑，使用固定部分（Tooling、Safety、Skills、Runtime）
- 工作区引导文件在「Workspace Files (injected)」下按顺序注入

固定部分顺序：
1. Tooling — 工具列表与使用说明
2. Safety — 简短防护提醒
3. Workspace Files (injected) — 以下为引导文件
4. 引导文件：identity → soul → agents → schedule → user → skills(可选)
5. Runtime — 当前时间、联网/文件/记忆等
"""

from pathlib import Path
from typing import Literal

from schedule_agent.config import Config

PromptMode = Literal["full", "minimal", "none"]
"""系统提示组装模式：

- full: 主 Agent，包含全部固定部分 + 引导文件
- minimal: 子 Agent，仅 Tooling + Safety + Runtime
- none: 仅 Identity（基本身份）
"""

DEFAULT_MAX_SECTION_CHARS = 8000
"""单 section 默认最大字符数，超出则截断并加标记"""

TRUNCATION_MARKER = "\n\n<!-- 内容过长，已截断 -->"
"""大文件截断后的标记"""


def _get_prompts_dir() -> Path:
    """获取 prompts 包根目录"""
    return Path(__file__).resolve().parent


def _get_skills_dir() -> Path:
    """获取 prompts/skills 目录路径"""
    return _get_prompts_dir() / "skills"


def _load_section(
    name: str,
    max_chars: int = DEFAULT_MAX_SECTION_CHARS,
) -> str:
    """
    加载 prompts/system/{name}.md 片段。
    空文件或仅空白内容返回空字符串。超出 max_chars 时截断并追加 TRUNCATION_MARKER。
    """
    path = _get_prompts_dir() / "system" / f"{name}.md"
    if not path.exists():
        return ""
    content = path.read_text(encoding="utf-8").strip()
    if not content:
        return ""
    if len(content) > max_chars:
        content = content[:max_chars].rstrip() + TRUNCATION_MARKER
    return content


def _load_skill(
    skill_name: str,
    max_chars: int = DEFAULT_MAX_SECTION_CHARS,
) -> str:
    """加载 prompts/skills/{skill_name}/SKILL.md。符合 AgentSkills/OpenClaw 规范。"""
    path = _get_skills_dir() / skill_name / "SKILL.md"
    if not path.exists():
        return ""
    content = path.read_text(encoding="utf-8").strip()
    if not content:
        return ""
    if len(content) > max_chars:
        content = content[:max_chars].rstrip() + TRUNCATION_MARKER
    return content


def _maybe_append(parts: list, content: str) -> None:
    """非空 content 则追加到 parts"""
    if content and content.strip():
        parts.append(content.strip())


def _load_user_section(max_chars: int = DEFAULT_MAX_SECTION_CHARS) -> str:
    """加载 USER。优先 user.md，不存在时回退 user.example.md。"""
    system_dir = _get_prompts_dir() / "system"
    path = system_dir / "user.md"
    if not path.exists():
        path = system_dir / "user.example.md"
    if not path.exists():
        return ""
    content = path.read_text(encoding="utf-8").strip()
    if not content:
        return ""
    if len(content) > max_chars:
        content = content[:max_chars].rstrip() + TRUNCATION_MARKER
    return content


def build_system_prompt(
    time_context: str,
    config: Config,
    has_web_extractor: bool,
    has_file_tools: bool = False,
    mode: PromptMode = "full",
    max_section_chars: int = DEFAULT_MAX_SECTION_CHARS,
    tool_mode: str = "full",
) -> str:
    """
    构建 Agent 系统提示。按 OpenClaw 风格固定部分 + 工作区引导注入顺序组装。
    """
    parts: list[str] = []
    load = lambda name: _load_section(name, max_section_chars)

    # ---------- 1. Tooling（工具列表与使用说明）----------
    if mode in ("full", "minimal"):
        if (tool_mode or "full").lower() == "kernel":
            _maybe_append(parts, load("tools_kernel"))
        else:
            _maybe_append(parts, load("tools"))

    # ---------- 2. Safety（简短防护）----------
    if mode in ("full", "minimal"):
        _maybe_append(parts, load("runtime_safety"))

    if mode == "none":
        _maybe_append(parts, load("identity"))
        return "\n\n".join(parts)

    # ---------- 3. Workspace Files (injected) — 以下为引导文件 ----------
    if mode == "full":
        parts.append("---\n# Workspace Files (injected)\n以下为工作区引导文件，已注入。\n---")

    # ---------- 4. 引导文件顺序：IDENTITY → SOUL → AGENTS → SCHEDULE → USER → SKILLS ----------
    if mode == "full":
        _maybe_append(parts, load("identity"))
        _maybe_append(parts, load("soul"))
        _maybe_append(parts, load("agents"))
        _maybe_append(parts, load("schedule"))
        user_content = _load_user_section(max_section_chars)
        if user_content:
            parts.append(user_content)
        for skill_name in (config.skills.enabled or []):
            _maybe_append(parts, _load_skill(skill_name, max_section_chars))

    # ---------- 5. Runtime（当前时间、联网/文件/记忆）----------
    if mode in ("full", "minimal"):
        time_section = load("runtime_time")
        if time_section:
            _maybe_append(parts, time_section.format(time_context=time_context))
        if config.llm.enable_search and config.llm.provider == "qwen":
            web_capabilities = [
                "- 当前新闻、热点事件",
                "- 实时天气信息",
                "- 股票价格、汇率等金融数据",
                "- 最新技术资讯、行业动态",
                "- 其他需要实时更新的信息",
            ]
            web_search = load("runtime_web_search")
            if web_search:
                _maybe_append(parts, web_search.format(capabilities="\n".join(web_capabilities)))
        if has_web_extractor:
            _maybe_append(parts, load("runtime_web_extractor"))
        if has_file_tools:
            _maybe_append(parts, load("runtime_file_tools"))
        if config.memory.enabled:
            _maybe_append(parts, load("runtime_memory"))

    return "\n\n".join(parts)
