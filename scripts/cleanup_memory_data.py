"""
Utility script to migrate and tidy memory data under data/memory.

目标（面向当前 v2 记忆架构）:
- 将旧版长期记忆 entries.jsonl / markdown 迁移到按 user_id 命名空间的目录结构。
- 将早期的短期记忆和对话历史数据库标记为 legacy，避免与新路径混用。

该脚本只操作本地 JSON/Markdown/SQLite 文件，不修改任何业务代码。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

from agent.config import get_config
from agent.core.memory import LongTermMemory, MemoryEntry


def _migrate_long_term_entries(user_id: str = "root") -> Dict[str, Any]:
    """
    将旧版长期记忆 entries.jsonl 迁移到 long_term/<user_id>/entries.jsonl。

    迁移来源：
    - long_term/entries.jsonl
    - long_term/cli/entries.jsonl
    """
    cfg = get_config()
    base_dir = Path(cfg.memory.long_term_dir)
    legacy_files = [
        base_dir / "entries.jsonl",
        base_dir / "cli" / "entries.jsonl",
    ]

    target_dir = base_dir / user_id
    target_dir.mkdir(parents=True, exist_ok=True)

    long_term = LongTermMemory(
        storage_dir=str(target_dir),
        memory_md_path=str(target_dir / "MEMORY.md"),
        qmd_enabled=cfg.memory.qmd_enabled,
        qmd_command=cfg.memory.qmd_command,
    )

    existing_ids = {e.id for e in long_term.entries}
    imported = 0
    seen_sources: List[str] = []

    for src_path in legacy_files:
        if not src_path.exists():
            continue
        seen_sources.append(str(src_path))
        with src_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(data, dict):
                    continue
                entry_id = data.get("id")
                if isinstance(entry_id, str) and entry_id in existing_ids:
                    continue
                try:
                    entry = MemoryEntry.from_dict(data)
                except Exception:
                    continue
                # 与 LongTermMemory.add_recent_topic 的写入方式保持一致
                long_term._entries.append(entry)  # type: ignore[attr-defined]
                long_term._append_entry(entry)  # type: ignore[attr-defined]
                existing_ids.add(entry.id)
                imported += 1

    # 将旧 entries.jsonl 标记为 legacy，避免之后误用
    for src_path in legacy_files:
        if src_path.exists():
            legacy = src_path.with_name(src_path.stem + ".legacy" + src_path.suffix)
            if not legacy.exists():
                src_path.rename(legacy)

    return {
        "imported": imported,
        "sources": seen_sources,
        "target_entries": str(target_dir / "entries.jsonl"),
    }


def _migrate_long_term_markdown(user_id: str = "root") -> Dict[str, Any]:
    """
    将 long_term/markdown/*.md 迁移到 long_term/<user_id>/markdown。

    仅移动文件，不修改内容；适配新版 LongTermMemory 和 QMD 语义检索。
    """
    cfg = get_config()
    base_dir = Path(cfg.memory.long_term_dir)
    legacy_md_dir = base_dir / "markdown"
    if not legacy_md_dir.exists():
        return {"moved": 0, "source_dir": str(legacy_md_dir)}

    target_md_dir = base_dir / user_id / "markdown"
    target_md_dir.mkdir(parents=True, exist_ok=True)

    moved = 0
    for md_file in sorted(legacy_md_dir.glob("*.md")):
        target_path = target_md_dir / md_file.name
        if target_path.exists():
            # 若目标已存在，保留目标，跳过旧文件
            continue
        md_file.rename(target_path)
        moved += 1

    # 若目录已空，可以选择保留空目录以示兼容，也可以手动删除
    return {
        "moved": moved,
        "source_dir": str(legacy_md_dir),
        "target_dir": str(target_md_dir),
    }


def _mark_short_term_legacy() -> Dict[str, Any]:
    """
    将早期的短期记忆文件 sessions.jsonl 标记为 legacy，避免与新路径混用。
    """
    cfg = get_config()
    short_base = Path(cfg.memory.short_term_dir)
    legacy_file = short_base / "sessions.jsonl"
    if not legacy_file.exists():
        return {"renamed": False}

    backup = short_base / "sessions.legacy.jsonl"
    if backup.exists():
        # 已经处理过
        return {"renamed": False, "path": str(backup)}

    short_base.mkdir(parents=True, exist_ok=True)
    legacy_file.rename(backup)
    return {"renamed": True, "path": str(backup)}


def _mark_chat_history_legacy() -> Dict[str, Any]:
    """
    将旧版对话历史数据库标记为 legacy：
    - data/memory/chat_history.db
    - data/memory/chat_history.cli.db

    新版会按 user_id 使用 chat_history.<user_id>.db。
    """
    cfg = get_config()
    base_path = Path(cfg.memory.chat_history_db_path)
    base_dir = base_path.parent

    candidates: List[Path] = [
        base_path,
        base_dir / "chat_history.cli.db",
    ]

    renamed: List[Tuple[str, str]] = []
    for p in candidates:
        if not p.exists():
            continue
        if p.name.endswith(".legacy"):
            continue
        backup = p.with_name(p.name + ".legacy")
        if backup.exists():
            continue
        p.rename(backup)
        renamed.append((str(p), str(backup)))

    return {"renamed": renamed}


def _mark_memory_md_legacy() -> Dict[str, Any]:
    """
    将 long_term 下按 source 拆分的 MEMORY.md 标记为 legacy：
    - data/memory/long_term/root/MEMORY.md
    - data/memory/long_term/cli/MEMORY.md

    当前架构下，MEMORY.md 仅使用根目录下的全局配置路径（通常为 ./MEMORY.md）。
    """
    cfg = get_config()
    base_dir = Path(cfg.memory.long_term_dir)
    candidates = [
        base_dir / "root" / "MEMORY.md",
        base_dir / "cli" / "MEMORY.md",
    ]
    renamed: List[Tuple[str, str]] = []
    for p in candidates:
        if not p.exists():
            continue
        backup = p.with_name(p.name + ".legacy")
        if backup.exists():
            continue
        p.rename(backup)
        renamed.append((str(p), str(backup)))
    return {"renamed": renamed}


def main() -> None:
    user_id = (Path(".env").read_text(encoding="utf-8") if False else "root")  # placeholder, we always default
    # 实际上 user_id 由 SCHEDULE_USER_ID 控制；这里的数据迁移主要面向 root 命名空间。
    user_id = "root"

    lt_entries = _migrate_long_term_entries(user_id=user_id)
    lt_md = _migrate_long_term_markdown(user_id=user_id)
    stm = _mark_short_term_legacy()
    ch = _mark_chat_history_legacy()
    md = _mark_memory_md_legacy()

    print(
        "[cleanup_memory_data] "
        f"long_term_entries_imported={lt_entries['imported']} "
        f"from={lt_entries['sources']} "
        f"-> {lt_entries['target_entries']}"
    )
    print(
        "[cleanup_memory_data] "
        f"long_term_markdown_moved={lt_md['moved']} "
        f"from={lt_md.get('source_dir')} -> {lt_md.get('target_dir')}"
    )
    print(
        "[cleanup_memory_data] "
        f"short_term_legacy_renamed={stm.get('renamed')} "
        f"path={stm.get('path')}"
    )
    print(
        "[cleanup_memory_data] "
        f"chat_history_renamed={len(ch.get('renamed', []))} "
        f"details={ch.get('renamed')}"
    )
    print(
        "[cleanup_memory_data] "
        f"memory_md_renamed={len(md.get('renamed', []))} "
        f"details={md.get('renamed')}"
    )


if __name__ == "__main__":
    main()

