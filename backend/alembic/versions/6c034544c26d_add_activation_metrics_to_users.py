"""add activation metrics to users (활성화 계측 — 가입/프로필완성/첫 안전판정)

Revision ID: 6c034544c26d
Revises: f7c4a2e18b53
Create Date: 2026-08-11 00:00:00.000000

신규 가입자의 활성화 2단계(프로필 완성 → 첫 안전 판정)를 서버에서 계측하기 위한
타임스탬프 3종. admin 통계(GET /admin/stats/activation)의 원천 데이터.

⚠️ 기존 행 backfill 금지 — 계측 도입 이전 가입자의 실제 가입일을 우리는 모른다.
지어내면(예: 오늘 날짜로 채움) admin 통계가 "오늘 다 가입한 것"처럼 왜곡된다.
세 컬럼 전부 nullable=True, server_default 없음 → 기존 행은 전부 NULL 로 남는다.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '6c034544c26d'
down_revision: Union[str, None] = 'f7c4a2e18b53'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('created_at', sa.DateTime(), nullable=True))
    op.add_column('users', sa.Column('profile_completed_at', sa.DateTime(), nullable=True))
    op.add_column('users', sa.Column('first_activation_at', sa.DateTime(), nullable=True))
    op.create_index(op.f('ix_users_created_at'), 'users', ['created_at'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_users_created_at'), table_name='users')
    op.drop_column('users', 'first_activation_at')
    op.drop_column('users', 'profile_completed_at')
    op.drop_column('users', 'created_at')
