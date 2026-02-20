#!/usr/bin/env python3
"""
Schedule Agent CLI 入口

提供命令行交互界面，允许用户通过自然语言与日程管理 Agent 进行交互。
"""

import asyncio
import sys
from typing import List, Optional

from schedule_agent.config import Config, get_config
from schedule_agent.core import ScheduleAgent
from schedule_agent.cli import run_interactive_loop
from schedule_agent.utils.session_logger import SessionLogger
from schedule_agent.core.tools import (
    BaseTool,
    ParseTimeTool,
    AddEventTool,
    AddTaskTool,
    GetEventsTool,
    GetTasksTool,
    UpdateEventTool,
    UpdateTaskTool,
    DeleteScheduleDataTool,
    ReadFileTool,
    WriteFileTool,
    ModifyFileTool,
    GetFreeSlotsTool,
    PlanTasksTool,
    WebExtractorTool,
)


def get_default_tools(config: Optional[Config] = None) -> List[BaseTool]:
    """
    获取默认的工具列表。

    Args:
        config: 配置对象，用于判断是否启用网页抓取、文件读写等工具

    Returns:
        工具实例列表
    """
    tools: List[BaseTool] = [
        ParseTimeTool(),
        AddEventTool(),
        AddTaskTool(),
        GetEventsTool(),
        GetTasksTool(),
        UpdateEventTool(),
        UpdateTaskTool(),
        DeleteScheduleDataTool(),
        GetFreeSlotsTool(),
        PlanTasksTool(),
    ]

    # 文件读写工具（读取、写入、修改，写入/修改需配置允许）
    if config and config.file_tools.enabled:
        tools.append(ReadFileTool(config=config))
        tools.append(WriteFileTool(config=config))
        tools.append(ModifyFileTool(config=config))

    # 如果配置支持网页抓取（provider=qwen），添加网页抓取工具
    if config and config.llm.provider == "qwen":
        # 检查是否配置了网页抓取相关设置（即使 enable_web_extractor=false，工具也可以工作）
        # 工具内部会创建自己的配置
        tools.append(WebExtractorTool(config=config))
    
    return tools


def _load_config() -> Optional[Config]:
    """
    加载配置文件。

    Returns:
        Config 对象，如果加载失败返回 None
    """
    try:
        return get_config()
    except FileNotFoundError as e:
        print(f"错误: {str(e)}")
        print("请确保 config.yaml 文件存在并正确配置。")
        sys.exit(1)
    except Exception as e:
        print(f"加载配置失败: {str(e)}")
        sys.exit(1)


async def run_single_command(agent: ScheduleAgent, command: str) -> str:
    """
    执行单条命令。

    Args:
        agent: ScheduleAgent 实例
        command: 命令字符串

    Returns:
        Agent 的响应
    """
    return await agent.process_input(command)


async def main_async(args: Optional[List[str]] = None):
    """
    异步主函数。

    Args:
        args: 命令行参数
    """
    # 加载配置
    config = _load_config()
    if config is None:
        return

    # 获取默认工具
    tools = get_default_tools(config=config)

    # 创建 Session 日志记录器（若启用）
    session_logger = None
    if config.logging.enable_session_log:
        session_logger = SessionLogger(
            log_dir=config.logging.session_log_dir,
            enable_detailed_log=config.logging.enable_detailed_log,
            max_system_prompt_log_len=config.logging.max_system_prompt_log_len,
        )
        session_logger.on_session_start()

    agent_ref = None
    try:
        async with ScheduleAgent(
            config=config,
            tools=tools,
            max_iterations=config.agent.max_iterations,
            timezone=config.time.timezone,
            session_logger=session_logger,
        ) as agent:
            agent_ref = agent
            # 检查是否有命令行参数
            if args and len(args) > 1:
                # 执行单条命令
                command = " ".join(args[1:])
                response = await run_single_command(agent, command)
                print(response)
            else:
                # 运行交互式循环
                await run_interactive_loop(agent)
    finally:
        if session_logger:
            turn_count = agent_ref.get_turn_count() if agent_ref else 0
            total_usage = agent_ref.get_token_usage() if agent_ref else None
            session_logger.on_session_end(turn_count, total_usage)
            session_logger.close()


def main():
    """CLI 入口点"""
    asyncio.run(main_async(sys.argv))


if __name__ == "__main__":
    main()
