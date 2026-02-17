#!/bin/bash
# =============================================================================
# run-automation.sh - Schedule Agent 自动化开发循环
# =============================================================================
# 参考 Anthropic《Effective harnesses for long-running agents》规范
# 循环运行 Claude Code 完成 feature_list.json 中的任务
#
# 用法:
#   ./run-automation.sh 5        # 运行 5 次循环
#   ./run-automation.sh          # 默认运行 1 次
# =============================================================================

# 颜色
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# 日志目录
LOG_DIR="./automation-logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/automation-$(date +%Y%m%d_%H%M%S).log"

# 工具函数
log() {
    local level=$1
    local message=$2
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    echo -e "${timestamp} [${level}] ${message}" >> "$LOG_FILE"

    case $level in
        INFO)    echo -e "${BLUE}[INFO]${NC} ${message}" ;;
        SUCCESS) echo -e "${GREEN}[SUCCESS]${NC} ${message}" ;;
        WARNING) echo -e "${YELLOW}[WARNING]${NC} ${message}" ;;
        ERROR)   echo -e "${RED}[ERROR]${NC} ${message}" ;;
        PROGRESS) echo -e "${CYAN}[PROGRESS]${NC} ${message}" ;;
    esac
}

# 统计未完成任务
count_remaining_tasks() {
    if [ -f "feature_list.json" ]; then
        # 使用 Python 统计 passes: false 的数量
        python3 -c "
import json
with open('feature_list.json') as f:
    data = json.load(f)
count = sum(1 for f in data.get('features', []) if not f.get('passes', False))
print(count)
" 2>/dev/null || echo "0"
    else
        echo "0"
    fi
}

# 参数解析
TOTAL_RUNS=${1:-1}

if ! [[ "$TOTAL_RUNS" =~ ^[0-9]+$ ]]; then
    echo "用法: $0 [次数]"
    echo "示例: $0 5"
    exit 1
fi

# =============================================================================
# 启动
# =============================================================================

echo ""
echo "========================================"
echo " Schedule Agent - 自动化开发循环"
echo "========================================"
echo ""

log "INFO" "启动自动化循环，共 $TOTAL_RUNS 次"
log "INFO" "日志文件: $LOG_FILE"

# 检查必要文件
if [ ! -f "feature_list.json" ]; then
    log "ERROR" "未找到 feature_list.json"
    exit 1
fi

if [ ! -f "init.sh" ]; then
    log "ERROR" "未找到 init.sh"
    exit 1
fi

# 初始任务计数
INITIAL_TASKS=$(count_remaining_tasks)
log "INFO" "初始未完成任务: $INITIAL_TASKS"

# =============================================================================
# 主循环
# =============================================================================

for ((run=1; run<=TOTAL_RUNS; run++)); do
    echo ""
    echo "========================================"
    log "PROGRESS" "第 $run / $TOTAL_RUNS 次循环"
    echo "========================================"
    # 重新加载环境
    source init.sh
    # 检查剩余任务
    REMAINING=$(count_remaining_tasks)

    if [ "$REMAINING" -eq 0 ]; then
        log "SUCCESS" "所有任务已完成！"
        exit 0
    fi

    log "INFO" "当前未完成任务: $REMAINING"

    # 运行时间戳
    RUN_START=$(date +%s)
    RUN_LOG="$LOG_DIR/run-${run}-$(date +%Y%m%d_%H%M%S).log"

    log "INFO" "运行日志: $RUN_LOG"

    # 创建临时提示文件
    PROMPT_FILE=$(mktemp)
    cat > "$PROMPT_FILE" << 'PROMPT_EOF'
请按照 CLAUDE.md 中的工作流程执行下一个任务：

## 工作流程

### 1. 初始化环境
环境已初始化完成。请直接进入下一步。

### 2. 读取项目状态
- 读取 `claude-progress.txt` 了解之前的进度
- 读取 `feature_list.json` 找到下一个 `passes: false` 的任务
- 查看最近的 git log 了解最近的改动

### 3. 实现任务
- 根据任务描述的 steps 逐步实现
- 遵循现有代码风格和架构
- 每完成一个步骤都可以运行测试验证

### 4. 测试验证
- 运行 `pytest tests/ -v` 确保测试通过
- 如果有核心模块改动，确保 import 正常

### 5. 更新进度
在 `claude-progress.txt` 中记录：
```
## [日期] - 任务: [任务ID和描述]
### 完成内容:
- [具体改动]
### 测试:
- [如何验证]
### 备注:
- [任何注意事项]
```

### 6. 提交更改
**重要：所有更改必须在同一个 commit 中提交！**

1. 更新 `feature_list.json`，将任务的 `passes` 改为 `true`
2. 更新 `claude-progress.txt`
3. 一次性提交：
   ```bash
   git add .
   git commit -m "[任务ID] 完成任务描述"
   ```

## 重要规则

- 一个会话只完成**一个任务**
- 只有所有步骤验证通过后才标记 `passes: true`
- 永远不要删除任务，只改变 `passes` 状态
- 如果遇到阻塞问题，记录在 progress 中并停止，不要提交

现在开始执行下一个任务。
PROMPT_EOF

    # 运行 Claude Code
    log "INFO" "启动 Claude Code..."

    # PROMPT_CONTENT=$(cat "$PROMPT_FILE")

    if stdbuf -oL -eL claude -p \
        --dangerously-skip-permissions \
        --allowed-tools "Bash Edit Read Write Glob Grep Task WebSearch WebFetch mcp__playwright__*" \
        < "$PROMPT_FILE" 2>&1 | tee "$RUN_LOG"; then

        RUN_END=$(date +%s)
        RUN_DURATION=$((RUN_END - RUN_START))
        log "SUCCESS" "第 $run 次循环完成，耗时 ${RUN_DURATION} 秒"
    else
        RUN_END=$(date +%s)
        RUN_DURATION=$((RUN_END - RUN_START))
        log "WARNING" "第 $run 次循环异常退出，耗时 ${RUN_DURATION} 秒"
    fi

    # 清理临时文件
    rm -f "$PROMPT_FILE"

    # 检查任务完成情况
    REMAINING_AFTER=$(count_remaining_tasks)
    COMPLETED=$((REMAINING - REMAINING_AFTER))

    if [ "$COMPLETED" -gt 0 ]; then
        log "SUCCESS" "本次完成了 $COMPLETED 个任务"
    else
        log "WARNING" "本次未完成任何任务"
    fi

    log "INFO" "剩余任务: $REMAINING_AFTER"

    # 日志分隔
    echo "" >> "$LOG_FILE"
    echo "----------------------------------------" >> "$LOG_FILE"

    # 循环间隔
    if [ $run -lt $TOTAL_RUNS ]; then
        log "INFO" "等待 2 秒后继续..."
        sleep 2
    fi
done

# =============================================================================
# 总结
# =============================================================================

echo ""
echo "========================================"
log "SUCCESS" "自动化循环完成！"
echo "========================================"

FINAL_REMAINING=$(count_remaining_tasks)
TOTAL_COMPLETED=$((INITIAL_TASKS - FINAL_REMAINING))

echo ""
log "INFO" "总结:"
log "INFO" "  - 总运行次数: $TOTAL_RUNS"
log "INFO" "  - 完成任务数: $TOTAL_COMPLETED"
log "INFO" "  - 剩余任务数: $FINAL_REMAINING"
log "INFO" "  - 日志目录: $LOG_DIR"

if [ "$FINAL_REMAINING" -eq 0 ]; then
    log "SUCCESS" "所有任务已完成！"
else
    log "WARNING" "仍有任务未完成，可继续运行"
fi
