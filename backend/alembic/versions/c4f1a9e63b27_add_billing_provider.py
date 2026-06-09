"""add billing_provider to users

Revision ID: c4f1a9e63b27
Revises: b3e9c1a52f80
Create Date: 2026-06-08 16:00:00.000000

빌링키 발급 PG 구분 (toss | payple). 자동결제 갱신 시 어느 PG API 로
청구할지 결정. 페이플 정기결제 추가 대비.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c4f1a9e63b27'
down_revision: Union[str, None] = 'b3e9c1a52f80'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('billing_provider', sa.String(20), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'billing_provider')
