"""
Utility script to tidy automation data files under data/automation.

目标：
- 精简过时的 JobRun 记录，避免历史噪音和无效 job_id。
- 规范 automation_activity.jsonl 记录结构，兼容最新的工具与 CLI 展示逻辑。

仅影响本地 JSON 数据文件，不修改任何业务代码。
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from schedule_agent.automation.repositories import (
    JobDefinitionRepository,
    JobRunRepository,
    _automation_base_dir,
)


def cleanup_job_runs(keep_per_job: int = 20) -> Dict[str, Any]:
    """
    精简 job_runs.json：按 job_id 分组，仅保留每个 job 最近 N 条记录。

    Returns:
        简要统计信息字典。
    """
    repo = JobRunRepository()
    runs = repo.get_all()
    by_job: Dict[str, List[Any]] = {}
    for run in runs:
        by_job.setdefault(run.job_id, []).append(run)

    for job_id, items in by_job.items():
        items.sort(key=lambda r: r.triggered_at, reverse=True)

    kept: List[Any] = []
    for job_id, items in by_job.items():
        kept.extend(items[: max(1, keep_per_job)])

    # 重新写入精简后的数据
    repo.clear()
    for run in kept:
        repo.create(run)

    return {
        "total_before": len(runs),
        "total_after": len(kept),
        "job_count": len(by_job),
    }


def normalize_automation_activity(limit: int | None = None) -> Dict[str, Any]:
    """
    规范 automation_activity.jsonl 结构：
    - 若仅存在 result_snippet，则补齐 result = {success, message, error} 字段。
    - 若 operations 为字符串列表，则转换为对象列表，方便后续扩展。

    Args:
        limit: 可选，仅处理最近 N 条（默认处理全部）。
    """
    base_dir = _automation_base_dir()
    path = base_dir / "automation_activity.jsonl"
    if not path.exists():
        return {"processed": 0, "updated": 0}

    text = path.read_text(encoding="utf-8")
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if limit is not None and limit > 0:
        target_lines = lines[-limit:]
    else:
        target_lines = lines

    updated_records: List[Dict[str, Any]] = []
    updated_count = 0

    for line in target_lines:
        try:
            rec = json.loads(line)
        except Exception:
            # 跳过坏行
            continue

        changed = False

        # 1) 兼容旧格式：只有 result_snippet 时，补齐 result 结构
        result = rec.get("result")
        if not isinstance(result, dict):
            snippet = rec.get("result_snippet") or ""
            status = str(rec.get("status") or "").lower()
            success = status == "success"
            error = rec.get("error")
            rec["result"] = {
                "success": success,
                "message": snippet,
                "error": error,
            }
            changed = True

        # 2) 兼容旧格式：operations 为字符串列表时转为对象列表
        ops = rec.get("operations")
        if isinstance(ops, list) and ops and isinstance(ops[0], str):
            rec["operations"] = [
                {
                    "operation": name,
                    "success": None,
                    "message": None,
                    "error": None,
                }
                for name in ops
                if isinstance(name, str) and name.strip()
            ]
            changed = True

        if changed:
            updated_count += 1
        updated_records.append(rec)

    # 若 limit 生效，只重写最近 N 条，其余保持原样
    if limit is not None and limit > 0 and len(lines) > limit:
        prefix = lines[: len(lines) - len(updated_records)]
        new_lines = prefix + [json.dumps(r, ensure_ascii=False) for r in updated_records]
    else:
        new_lines = [json.dumps(r, ensure_ascii=False) for r in updated_records]

    path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

    return {
        "processed": len(target_lines),
        "updated": updated_count,
    }


def main() -> None:
    job_stats = cleanup_job_runs(keep_per_job=20)
    activity_stats = normalize_automation_activity()

    print(
        "[cleanup_automation_data] "
        f"job_runs: {job_stats['total_before']} -> {job_stats['total_after']} "
        f"(jobs={job_stats['job_count']}), "
        f"activity: processed={activity_stats['processed']}, updated={activity_stats['updated']}"
    )


if __name__ == "__main__":
    main()

