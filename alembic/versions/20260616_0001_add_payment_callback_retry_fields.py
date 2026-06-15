"""add payment callback retry fields

Revision ID: 20260616_0001
Revises:
Create Date: 2026-06-16 00:30:00

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '20260616_0001'
down_revision = '20260610_0024'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 添加重试相关字段到 payment_callbacks 表
    op.add_column('payment_callbacks', sa.Column('retry_count', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('payment_callbacks', sa.Column('last_retry_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('payment_callbacks', sa.Column('failure_reason', sa.Text(), nullable=True))


def downgrade() -> None:
    # 回滚时删除这些字段
    op.drop_column('payment_callbacks', 'failure_reason')
    op.drop_column('payment_callbacks', 'last_retry_at')
    op.drop_column('payment_callbacks', 'retry_count')
