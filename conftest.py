"""
Pytest 全局配置 - 测试隔离

确保测试期间写入的数据不会污染项目的 data/ 目录。
测试时使用临时目录存储数据，测试结束后自动清理。
"""

import os
import tempfile
from pathlib import Path

import pytest


# 用于 pytest_unconfigure 清理
_test_data_dir: str | None = None


def pytest_configure(config):
    """测试会话开始前：创建临时数据目录并设置环境变量"""
    global _test_data_dir
    tmp = tempfile.mkdtemp(prefix="schedule_agent_test_")
    _test_data_dir = tmp
    os.environ["SCHEDULE_AGENT_TEST_DATA_DIR"] = tmp


def pytest_unconfigure(config):
    """测试会话结束后：清除环境变量并删除临时目录"""
    global _test_data_dir
    if "SCHEDULE_AGENT_TEST_DATA_DIR" in os.environ:
        del os.environ["SCHEDULE_AGENT_TEST_DATA_DIR"]
    if _test_data_dir and Path(_test_data_dir).exists():
        import shutil

        try:
            shutil.rmtree(_test_data_dir, ignore_errors=True)
        except OSError:
            pass
    _test_data_dir = None
