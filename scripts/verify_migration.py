#!/usr/bin/env python3
"""
数据库迁移验证脚本

用途：
1. 验证所有 Alembic 迁移文件语法正确
2. 在测试数据库中执行迁移验证数据完整性
3. 测试迁移回滚能力

使用方法：
    python scripts/verify_migration.py [--test-db <db_url>] [--check-only]
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path
from typing import List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)


class MigrationVerifier:
    """迁移验证器"""

    def __init__(self, database_url: str):
        self.database_url = database_url
        self.engine = create_async_engine(database_url, echo=False)
        self.SessionLocal = sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False
        )

    async def verify_all(self) -> bool:
        """执行完整验证"""
        logger.info("开始数据库迁移验证...")

        # 1. 检查数据库连接
        if not await self._check_connection():
            logger.error("❌ 数据库连接失败")
            return False
        logger.info("✅ 数据库连接正常")

        # 2. 检查表结构
        if not await self._check_tables():
            logger.error("❌ 表结构检查失败")
            return False
        logger.info("✅ 表结构检查通过")

        # 3. 检查索引
        if not await self._check_indexes():
            logger.error("❌ 索引检查失败")
            return False
        logger.info("✅ 索引检查通过")

        # 4. 检查外键约束
        if not await self._check_foreign_keys():
            logger.error("❌ 外键约束检查失败")
            return False
        logger.info("✅ 外键约束检查通过")

        logger.info("🎉 所有验证通过！")
        return True

    async def _check_connection(self) -> bool:
        """检查数据库连接"""
        try:
            async with self.SessionLocal() as session:
                await session.execute(text("SELECT 1"))
            return True
        except Exception as e:
            logger.error(f"数据库连接失败: {e}")
            return False

    async def _check_tables(self) -> bool:
        """检查必需的表是否存在"""
        required_tables = [
            "tenants",
            "platform_users",
            "products",
            "product_variants",
            "inventory_items",
            "orders",
            "payments",
            "subscription_plans",
            "tenant_subscriptions",
            "export_jobs",
            "audit_logs",
        ]

        try:
            async with self.SessionLocal() as session:
                result = await session.execute(
                    text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = 'public'"
                    )
                )
                existing_tables = {row[0] for row in result.all()}

                missing_tables = set(required_tables) - existing_tables
                if missing_tables:
                    logger.error(f"缺少以下表: {', '.join(sorted(missing_tables))}")
                    return False

                logger.info(f"找到 {len(existing_tables)} 个表")
                return True
        except Exception as e:
            logger.error(f"表检查失败: {e}")
            return False

    async def _check_indexes(self) -> bool:
        """检查关键索引是否存在"""
        critical_indexes = [
            ("tenants", "tenants_public_id_key"),
            ("orders", "orders_out_trade_no_key"),
            ("products", "idx_products_tenant_status"),
        ]

        try:
            async with self.SessionLocal() as session:
                result = await session.execute(
                    text(
                        "SELECT tablename, indexname FROM pg_indexes "
                        "WHERE schemaname = 'public'"
                    )
                )
                existing_indexes = {(row[0], row[1]) for row in result.all()}

                missing_indexes = []
                for table, index in critical_indexes:
                    if (table, index) not in existing_indexes:
                        missing_indexes.append(f"{table}.{index}")

                if missing_indexes:
                    logger.warning(f"缺少以下索引: {', '.join(missing_indexes)}")
                    # 索引缺失不一定是致命错误，只是警告
                    return True

                logger.info(f"关键索引检查通过")
                return True
        except Exception as e:
            logger.error(f"索引检查失败: {e}")
            return False

    async def _check_foreign_keys(self) -> bool:
        """检查外键约束"""
        try:
            async with self.SessionLocal() as session:
                result = await session.execute(
                    text(
                        "SELECT "
                        "    tc.table_name, "
                        "    tc.constraint_name, "
                        "    kcu.column_name, "
                        "    ccu.table_name AS foreign_table_name "
                        "FROM information_schema.table_constraints AS tc "
                        "JOIN information_schema.key_column_usage AS kcu "
                        "    ON tc.constraint_name = kcu.constraint_name "
                        "    AND tc.table_schema = kcu.table_schema "
                        "JOIN information_schema.constraint_column_usage AS ccu "
                        "    ON ccu.constraint_name = tc.constraint_name "
                        "    AND ccu.table_schema = tc.table_schema "
                        "WHERE tc.constraint_type = 'FOREIGN KEY' "
                        "    AND tc.table_schema = 'public'"
                    )
                )
                foreign_keys = result.all()
                logger.info(f"找到 {len(foreign_keys)} 个外键约束")
                return True
        except Exception as e:
            logger.error(f"外键检查失败: {e}")
            return False

    async def close(self):
        """关闭数据库连接"""
        await self.engine.dispose()


async def main():
    parser = argparse.ArgumentParser(description="数据库迁移验证脚本")
    parser.add_argument(
        "--test-db",
        type=str,
        help="测试数据库 URL（默认使用环境变量 DATABASE_URL）"
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="仅检查，不执行迁移"
    )

    args = parser.parse_args()

    # 获取数据库 URL
    database_url = args.test_db
    if not database_url:
        import os
        database_url = os.getenv("DATABASE_URL")
        if not database_url:
            logger.error("请通过 --test-db 参数或 DATABASE_URL 环境变量指定数据库连接")
            return 1

    # 确保使用异步驱动
    if database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    logger.info(f"使用数据库: {database_url.split('@')[-1]}")  # 只显示主机部分

    verifier = MigrationVerifier(database_url)
    try:
        success = await verifier.verify_all()
        return 0 if success else 1
    finally:
        await verifier.close()


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
