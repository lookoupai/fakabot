#!/bin/sh
set -e

# 启动应用前自动执行数据库迁移，确保表结构与代码一致。
# 历史问题：曾经 docker-compose 只跑 uvicorn，从不执行 alembic upgrade head，
# 导致数据库为空、所有 worker 持续报 UndefinedTableError。
echo "[entrypoint] Running database migrations (alembic upgrade head)..."
alembic upgrade head
echo "[entrypoint] Migrations complete."

# 交由 CMD（uvicorn）接管进程，保持 PID 1 信号正确传递
exec "$@"
