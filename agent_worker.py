#!/usr/bin/env python3
"""Queue-driven Agent worker entrypoint.

Starts:
  1. AutomationScheduler (push mode) — periodically pushes AgentTask to the queue.
  2. TaskConsumer loop — polls the queue and runs each task through ScheduleAgent.

This is the new recommended background process. The old automation_worker.py
(direct service execution) is kept for compatibility during the transition period.

Usage::

    python agent_worker.py
"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys

from schedule_agent.automation.agent_task import TaskStatus
from schedule_agent.automation.repositories import (
    JobDefinitionRepository,
    JobRunRepository,
)
from schedule_agent.automation.scheduler import AutomationScheduler
from schedule_agent.automation.session_manager import SessionManager
from schedule_agent.automation.task_queue import AgentTaskQueue
from schedule_agent.automation.logging_utils import AutomationTaskLogger
from schedule_agent.config import get_config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("agent_worker")

POLL_INTERVAL_SECONDS = 5


def _sync_jobs_from_config(config, job_def_repo: JobDefinitionRepository) -> None:
    """根据 config.automation.jobs 确保对应 JobDefinition 存在/更新。

    设计原则：
    - 只新增或更新由配置声明的任务，不删除任何已有任务（包括默认内置任务和历史任务）。
    - 通过 (job_type, user_id, instruction) 三元组匹配已有记录，若存在则更新 interval 和 enabled。
    """
    automation_cfg = getattr(config, "automation", None)
    if not automation_cfg or not getattr(automation_cfg, "jobs", None):
        return

    existing = job_def_repo.get_all()

    for job_cfg in automation_cfg.jobs:
        times = getattr(job_cfg, "times", None) or []
        has_times = bool(times)
        has_daily_time = bool(getattr(job_cfg, "daily_time", None))

        # times / daily_time 模式：每天固定时刻执行一次，interval 仅作为回退与文档提示。
        if has_times or has_daily_time:
            interval_seconds = 24 * 3600
        else:
            try:
                interval_seconds = int(job_cfg.interval_minutes) * 60
            except Exception:
                # 跳过非法配置，避免影响其他任务。
                continue

            if interval_seconds <= 0:
                continue

        target_job_type = job_cfg.job_type
        target_user_id = job_cfg.user_id
        target_instruction = job_cfg.description

        matched = None
        for job in existing:
            payload = job.payload_template or {}
            if (
                job.job_type == target_job_type
                and str(payload.get("user_id", "default")) == target_user_id
                and str(payload.get("instruction", "")) == target_instruction
            ):
                matched = job
                break

        if matched is not None:
            changed = False
            if matched.interval_seconds != interval_seconds:
                matched.interval_seconds = interval_seconds
                changed = True
            # 同步 enabled 状态
            if matched.enabled != job_cfg.enabled:
                matched.enabled = job_cfg.enabled
                changed = True
            # 同步 payload 配置（daily_time / times / start_time 等）
            payload = matched.payload_template or {}
            if has_daily_time and payload.get("daily_time") != job_cfg.daily_time:
                payload["daily_time"] = job_cfg.daily_time
                changed = True
            if has_times and payload.get("times") != times:
                payload["times"] = list(times)
                changed = True
            if getattr(job_cfg, "start_time", None) and payload.get("start_time") != job_cfg.start_time:
                payload["start_time"] = job_cfg.start_time
                changed = True
            if changed:
                matched.payload_template = payload
            if changed:
                job_def_repo.update(matched)
        else:
            from schedule_agent.automation.types import JobDefinition

            job = JobDefinition(
                job_type=target_job_type,
                enabled=job_cfg.enabled,
                interval_seconds=interval_seconds,
                timezone=config.time.timezone,
                payload_template={
                    "instruction": target_instruction,
                    "user_id": target_user_id,
                    **(
                        {"daily_time": job_cfg.daily_time}
                        if has_daily_time
                        else {}
                    ),
                    **(
                        {"times": list(times)}
                        if has_times
                        else {}
                    ),
                    **(
                        {"start_time": job_cfg.start_time}
                        if getattr(job_cfg, "start_time", None)
                        else {}
                    ),
                },
            )
            job_def_repo.create(job)


async def _consume_loop(
    queue: AgentTaskQueue,
    session_manager: SessionManager,
    stop_event: asyncio.Event,
) -> None:
    """持续从队列取任务并交由 SessionManager / Agent 执行。"""
    while not stop_event.is_set():
        task = queue.pop_pending()
        if task is None:
            try:
                await asyncio.wait_for(
                    asyncio.shield(stop_event.wait()),
                    timeout=POLL_INTERVAL_SECONDS,
                )
            except asyncio.TimeoutError:
                pass
            continue

        task_logger = AutomationTaskLogger(task)
        task_logger.log_task_start()

        logger.info(
            "Running task %s | source=%s | session=%s | policy=%s",
            task.task_id,
            task.source,
            task.session_id,
            task.context_policy,
        )
        try:

            async def on_trace_event(event: dict) -> None:
                task_logger.log_trace_event(event)

            result = await session_manager.run_task(
                session_id=task.session_id,
                instruction=task.instruction,
                context_policy=task.context_policy,
                on_trace_event=on_trace_event,
            )
            op_ok, op_problems = task_logger.evaluate_required_operations()
            if op_ok:
                queue.update_status(task.task_id, TaskStatus.SUCCESS, result=result)
                task_logger.log_task_end(status=TaskStatus.SUCCESS, result=result, error=None)
                logger.info("Task %s succeeded", task.task_id)
            else:
                error_msg = "; ".join(op_problems)
                queue.update_status(task.task_id, TaskStatus.FAILED, result=result, error=error_msg)
                task_logger.log_task_end(status=TaskStatus.FAILED, result=result, error=error_msg)
                logger.warning("Task %s marked failed: %s", task.task_id, error_msg)
        except Exception as exc:
            logger.exception("Task %s failed: %s", task.task_id, exc)
            task_logger.log_task_end(status=TaskStatus.FAILED, result=None, error=str(exc))
            queue.update_status(task.task_id, TaskStatus.FAILED, error=str(exc))


async def _main() -> None:
    config = get_config()

    # 导入工具工厂（复用 main.py 中已定义好的工具列表逻辑）
    try:
        from main import get_default_tools  # type: ignore[import]
    except ImportError:
        logger.warning(
            "Could not import get_default_tools from main.py; "
            "agent will run with no tools registered."
        )
        get_default_tools = lambda cfg=None: []  # noqa: E731

    queue = AgentTaskQueue()

    # 恢复上次崩溃未完成的任务
    recovered = queue.recover_stale_running()
    if recovered:
        logger.info("Recovered %d stale running tasks as pending", recovered)

    session_manager = SessionManager(
        config=config,
        tools_factory=lambda: get_default_tools(config),
    )

    job_def_repo = JobDefinitionRepository()
    # 先将 config.automation.jobs 中声明的任务同步到 JobDefinitionRepository，
    # 再补齐内置默认任务，确保默认 job_type 仍然存在。
    _sync_jobs_from_config(config, job_def_repo)

    scheduler = AutomationScheduler(job_def_repo=job_def_repo, job_run_repo=JobRunRepository(), task_queue=queue)
    scheduler.ensure_default_jobs()
    await scheduler.start()

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)

    logger.info("Agent worker started. Polling every %ds.", POLL_INTERVAL_SECONDS)

    try:
        await _consume_loop(queue, session_manager, stop_event)
    finally:
        await scheduler.stop()
        await session_manager.close_all()
        logger.info("Agent worker stopped.")


if __name__ == "__main__":
    try:
        asyncio.run(_main())
    except (KeyboardInterrupt, asyncio.CancelledError):
        sys.exit(0)
