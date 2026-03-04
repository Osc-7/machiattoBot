"""Automation -> Core 命令模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict

from .models import AgentRunInput


@dataclass(frozen=True)
class RunTurnCommand:
    """执行普通输入轮次。"""

    session_id: str
    input: AgentRunInput
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class InjectMessageCommand:
    """从外部通道注入消息。"""

    session_id: str
    input: AgentRunInput
    source: str = "external"
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExpireSessionCommand:
    """触发会话切分指令。"""

    session_id: str
    reason: str = "session_expire"
    metadata: Dict[str, Any] = field(default_factory=dict)
