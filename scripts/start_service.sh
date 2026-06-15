#!/usr/bin/env bash
#
# FakaBot 服务启动脚本
#
# 用途：
# 1. 启动主 Web 服务（Uvicorn）
# 2. 启动所有 Worker 进程
# 3. 配置验证和健康检查
#

set -e

# 颜色输出
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# 项目根目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo -e "${GREEN}=== FakaBot 服务启动脚本 ===${NC}"
echo "项目路径: $PROJECT_ROOT"

# 切换到项目目录
cd "$PROJECT_ROOT"

# 1. 环境检查
echo ""
echo -e "${YELLOW}[1/5] 检查环境...${NC}"

if [ ! -f ".env" ]; then
    echo -e "${RED}错误: .env 文件不存在${NC}"
    exit 1
fi

if [ ! -d ".venv" ]; then
    echo -e "${RED}错误: Python 虚拟环境不存在${NC}"
    exit 1
fi

echo -e "${GREEN}✓ 环境检查通过${NC}"

# 2. 配置验证
echo ""
echo -e "${YELLOW}[2/5] 验证配置...${NC}"

# 加载环境变量
export $(grep -v '^#' .env | xargs)

# 检查必需的环境变量
REQUIRED_VARS="DATABASE_URL SECRET_KEY STORAGE_ROOT"
for var in $REQUIRED_VARS; do
    if [ -z "${!var}" ]; then
        echo -e "${RED}错误: 环境变量 $var 未设置${NC}"
        exit 1
    fi
done

echo -e "${GREEN}✓ 配置验证通过${NC}"

# 3. 数据库连接测试
echo ""
echo -e "${YELLOW}[3/5] 测试数据库连接...${NC}"

PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -c "
import asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

async def test_db():
    engine = create_async_engine('$DATABASE_URL', echo=False)
    async with engine.begin() as conn:
        await conn.execute(text('SELECT 1'))
    await engine.dispose()
    print('数据库连接成功')

asyncio.run(test_db())
" || {
    echo -e "${RED}错误: 数据库连接失败${NC}"
    exit 1
}

echo -e "${GREEN}✓ 数据库连接正常${NC}"

# 4. 启动选项
echo ""
echo -e "${YELLOW}[4/5] 启动服务...${NC}"

START_WEB=${START_WEB:-true}
START_WORKERS=${START_WORKERS:-false}
WEB_PORT=${WEB_PORT:-8000}
WEB_WORKERS=${WEB_WORKERS:-4}

echo "启动配置："
echo "  - Web 服务: $START_WEB (端口: $WEB_PORT, 工作进程: $WEB_WORKERS)"
echo "  - Worker 进程: $START_WORKERS"

# 5. 启动服务
echo ""
if [ "$START_WEB" = "true" ]; then
    echo -e "${GREEN}启动 Web 服务...${NC}"

    exec .venv/bin/uvicorn app.main:app \
        --host 0.0.0.0 \
        --port "$WEB_PORT" \
        --workers "$WEB_WORKERS" \
        --log-level info \
        --access-log
fi

if [ "$START_WORKERS" = "true" ]; then
    echo -e "${GREEN}启动 Worker 进程...${NC}"

    # 启动报表 Worker
    PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m workers.report_worker &
    REPORT_PID=$!
    echo "  - 报表 Worker (PID: $REPORT_PID)"

    # 启动订阅 Worker
    PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m workers.subscription_worker &
    SUBS_PID=$!
    echo "  - 订阅 Worker (PID: $SUBS_PID)"

    # 启动支付重试 Worker
    PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m workers.payment_retry_worker &
    PAYMENT_PID=$!
    echo "  - 支付重试 Worker (PID: $PAYMENT_PID)"

    # 等待所有 Worker
    wait $REPORT_PID $SUBS_PID $PAYMENT_PID
fi
