"""Agent Core 事件模型定义。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict


@dataclass(frozen=True)
class CoreEvent:
    """统一的 Core 事件结构。"""

    name: str
    payload: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.utcnow)
