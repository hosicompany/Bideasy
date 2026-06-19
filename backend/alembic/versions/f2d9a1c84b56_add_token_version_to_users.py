"""add token_version to users (JWT 무효화)

Revision ID: f2d9a1c84b56
Revises: e1a4c7b2f039
Create Date: 2026-06-19 00:00:00.000000

비밀번호 변경·로그아웃·강제 로그아웃 시 token_version 을 증가시켜
기존에 발급된 모든 JWT(옛 tv 클레임)를 즉시 무효화하기 위한 컬럼.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f2d9a1c84b56'
down_revision: Union[str, None] = 'e1a4c7b2f039'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'users',
        sa.Column('token_version', sa.Integer(), nullable=False, server_default='0'),
    )


def downgrade() -> None:
    op.drop_column('users', 'token_version')
