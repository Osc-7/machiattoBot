#!/bin/bash
# =============================================================================
# init.sh - Schedule Agent 环境初始化脚本 (Sandbox 优化版)
# =============================================================================

# 颜色定义
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[OK]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }

echo -e "${BLUE}>>> 正在初始化 Sandbox 开发环境...${NC}"

# 1. 确保 Python 路径正确 (Sandbox 通常直接使用 python3)
export PYTHONUNBUFFERED=1
PYTHON_BIN=$(which python3 || which python)

if [ -z "$PYTHON_BIN" ]; then
    echo -e "${RED}[ERROR]${NC} 未找到 Python 环境"
    return 1 2>/dev/null || exit 1
fi

# 2. 检查并安装依赖
# 在 Sandbox 中，我们通常直接 pip install 到系统或当前用户路径
if [ -f "requirements.txt" ]; then
    log_info "正在检查/更新依赖 (requirements.txt)..."
    $PYTHON_BIN -m pip install --upgrade pip -q
    $PYTHON_BIN -m pip install -r requirements.txt -q
    log_success "依赖检查完成"
fi

# 3. 设置 PYTHONPATH (确保当前目录下的模块可以被导入)
export PYTHONPATH=$PYTHONPATH:$(pwd)
log_info "PYTHONPATH 已设置: $PYTHONPATH"

# 4. 核心模块验证
if $PYTHON_BIN -c "from schedule_agent.main import ScheduleAgent" 2>/dev/null; then
    log_success "核心模块导入正常"
else
    log_warn "核心模块导入失败，请检查代码结构"
fi

echo -e "${GREEN}✅ 环境就绪 (${PYTHON_BIN})${NC}"