"""
Kernel Shell — 系统控制台交互式 Shell。

类似 OS 的终端：启动后出现提示符，输入命令即可查看/管理系统状态，无需写代码。

用法::
    python main.py shell
    或
    python -m system.kernel.shell

前提：automation daemon 已启动（python automation_daemon.py）。
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from system.automation import AutomationIPCClient


def _print_table(rows: List[Dict[str, Any]], columns: List[str], widths: Optional[Dict[str, int]] = None) -> None:
    """简单表格输出。"""
    widths = widths or {}
    for col in columns:
        if col not in widths:
            widths[col] = max(len(str(col)), max((len(str(r.get(col, ""))) for r in rows), default=0))
    fmt = "  ".join(f"{{:{widths.get(c, 12)}}}" for c in columns)
    print(fmt.format(*columns))
    print("-" * (sum(widths.get(c, 12) for c in columns) + 2 * (len(columns) - 1)))
    for r in rows:
        print(fmt.format(*(str(r.get(c, "")) for c in columns)))


async def run_kernel_shell(client: AutomationIPCClient) -> None:
    """
    运行 Kernel 系统控制台 Shell。

    循环：提示符 → 读入一行 → 解析命令 → 调用 IPC terminal_* → 打印结果。
    """
    print()
    print("  Kernel 系统控制台 (KernelTerminal)")
    print("  命令: ps | top | queue | inspect <sid> | kill <sid> | cancel <sid> | spawn <sid> | attach <sid> <text>")
    print("  help 帮助  quit/exit 退出")
    print()

    while True:
        try:
            try:
                line = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: input("kernel> ").strip()
                )
            except EOFError:
                print()
                break
            if not line:
                continue

            parts = line.split()
            cmd = parts[0].lower()
            args = parts[1:]

            if cmd in ("quit", "exit", "q"):
                print("再见。")
                break

            if cmd == "help":
                print("  ps                    列出所有活跃 Core")
                print("  top                   系统概览")
                print("  queue                 队列状态")
                print("  inspect <session_id>  查看某个 Core 详情")
                print("  kill <session_id>    终结 Core")
                print("  cancel <session_id>  取消该 session 正在运行的任务")
                print("  spawn <session_id>   创建新 Core")
                print("  attach <session_id> <text>  以系统身份向该 session 发消息")
                print("  help | quit | exit")
                continue

            if cmd == "ps":
                cores = await client.terminal_ps()
                if not cores:
                    print("  (无活跃 Core)")
                else:
                    # 格式化浮点数列便于表格显示
                    rows = []
                    for c in cores:
                        r = dict(c)
                        r["idle_seconds"] = int(r.get("idle_seconds", 0))
                        rows.append(r)
                    _print_table(
                        rows,
                        ["session_id", "source", "user_id", "mode", "idle_seconds", "total_tokens", "turn_count"],
                        {"session_id": 32, "source": 10, "user_id": 12, "mode": 10},
                    )
                continue

            if cmd == "top":
                status = await client.terminal_top()
                print(f"  active_cores:   {status.get('active_cores', 0)}")
                print(f"  max_cores:      {status.get('max_cores', 0)}")
                print(f"  queue_depth:    {status.get('queue_depth', 0)}")
                print(f"  inflight_tasks: {status.get('inflight_tasks', 0)}")
                print(f"  uptime_seconds: {status.get('uptime_seconds', 0):.0f}")
                continue

            if cmd == "queue":
                q = await client.terminal_queue()
                print(f"  queue_size:         {q.get('queue_size', 0)}")
                print(f"  active_task_count:  {q.get('active_task_count', 0)}")
                print(f"  inflight_sessions:  {q.get('inflight_sessions', {})}")
                print(f"  cancelled_sessions: {q.get('cancelled_sessions', [])}")
                continue

            if cmd == "inspect":
                if not args:
                    print("  用法: inspect <session_id>")
                    continue
                sid = args[0]
                try:
                    detail = await client.terminal_inspect(sid)
                    for k, v in detail.items():
                        print(f"  {k}: {v}")
                except Exception as e:
                    print(f"  错误: {e}")
                continue

            if cmd == "kill":
                if not args:
                    print("  用法: kill <session_id>")
                    continue
                try:
                    await client.terminal_kill(args[0])
                    print(f"  已终结: {args[0]}")
                except Exception as e:
                    print(f"  错误: {e}")
                continue

            if cmd == "cancel":
                if not args:
                    print("  用法: cancel <session_id>")
                    continue
                try:
                    cancelled = await client.terminal_cancel(args[0])
                    print(f"  取消任务: {cancelled}")
                except Exception as e:
                    print(f"  错误: {e}")
                continue

            if cmd == "spawn":
                if not args:
                    print("  用法: spawn <session_id> [--source X] [--user Y]")
                    continue
                sid = args[0]
                source, user = "system", "root"
                i = 1
                while i < len(args):
                    if args[i] == "--source" and i + 1 < len(args):
                        source = args[i + 1]
                        i += 2
                    elif args[i] == "--user" and i + 1 < len(args):
                        user = args[i + 1]
                        i += 2
                    else:
                        i += 1
                try:
                    info = await client.terminal_spawn(sid, source=source, user_id=user)
                    print(f"  已创建: {info.get('session_id', sid)}")
                except Exception as e:
                    print(f"  错误: {e}")
                continue

            if cmd == "attach":
                if len(args) < 2:
                    print("  用法: attach <session_id> <消息内容>")
                    continue
                sid = args[0]
                text = " ".join(args[1:])
                try:
                    result = await client.terminal_attach(sid, text)
                    print()
                    print(result.output_text or "(无文本回复)")
                    print()
                except Exception as e:
                    print(f"  错误: {e}")
                continue

            print(f"  未知命令: {cmd}  输入 help 查看帮助")

        except KeyboardInterrupt:
            print()
            continue


def main() -> None:
    """独立入口：python -m system.kernel.shell"""
    import os
    import sys
    from system.automation import default_socket_path

    async def _main() -> None:
        socket_path = os.environ.get("SCHEDULE_AUTOMATION_SOCKET", "").strip() or default_socket_path()
        client = AutomationIPCClient(socket_path=socket_path)
        if not await client.ping():
            print(f"错误: 未连接到 automation daemon ({socket_path})", file=sys.stderr)
            print("请先运行: python automation_daemon.py", file=sys.stderr)
            sys.exit(1)
        await client.connect()
        try:
            await run_kernel_shell(client)
        finally:
            await client.close()

    asyncio.run(_main())


if __name__ == "__main__":
    main()
