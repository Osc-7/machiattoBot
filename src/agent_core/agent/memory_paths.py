"""Helpers for agent memory path resolution and session identifiers."""

from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Dict, Optional

from agent_core.config import Config, MemoryConfig


def _namespace_dir(path: str, user_id: str) -> str:
    base = Path(path)
    return str(base / user_id)


def _namespace_file(path: str, user_id: str) -> str:
    base = Path(path)
    suffix = base.suffix
    stem = base.stem if suffix else base.name
    if suffix:
        return str(base.with_name(f"{stem}.{user_id}{suffix}"))
    return str(base.with_name(f"{stem}.{user_id}"))


def resolve_memory_owner_paths(
    mem_cfg: MemoryConfig,
    user_id: str,
    config: Optional[Config] = None,
    source: str = "cli",
) -> Dict[str, str]:
    """
    Compute storage paths for all memory layers under the current owner.

    When `source=="shuiyuan"` and Shuiyuan memory is enabled, use isolated paths.
    """
    if source == "shuiyuan" and config and getattr(config, "shuiyuan", None):
        shuiyuan_cfg = config.shuiyuan
        if shuiyuan_cfg.enabled and shuiyuan_cfg.memory:
            mem = shuiyuan_cfg.memory
            long_term = mem.long_term_dir
            base = Path(shuiyuan_cfg.db_path).parent
            return {
                "short_term_dir": str(Path(long_term).parent / "short_term" / "shuiyuan"),
                "long_term_dir": long_term,
                "content_dir": str(Path(long_term).parent / "content" / "shuiyuan"),
                "chat_history_db_path": str(base / "shuiyuan_chat_history.db"),
                "memory_md_path": str(Path(long_term) / "MEMORY.md"),
            }

    return {
        "short_term_dir": _namespace_dir(mem_cfg.short_term_dir, user_id),
        "long_term_dir": _namespace_dir(mem_cfg.long_term_dir, user_id),
        "content_dir": _namespace_dir(mem_cfg.content_dir, user_id),
        "chat_history_db_path": _namespace_file(mem_cfg.chat_history_db_path, user_id),
        "memory_md_path": mem_cfg.memory_md_path,
    }


def new_session_id() -> str:
    return f"sess-{int(time.time())}-{uuid.uuid4().hex[:6]}"
