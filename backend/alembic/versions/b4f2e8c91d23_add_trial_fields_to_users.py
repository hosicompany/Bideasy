"""add trial fields to users

Revision ID: b4f2e8c91d23
Revises: 798aa363dcb2
Create Date: 2026-05-27 23:45:00.000000

신규 가입 시 14일간 Pro 권한을 자동 부여하기 위한 컬럼 추가.
- trial_started_at: 체험 시작 시각 (None = 아직 체험 시작 안 함)
- trial_expires_at: 체험 만료 시각 (None = 체험 없음)

체험 재사용 방지: trial_started_at 이 None 이 아닌 경우 새 체험 시작 불가.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b4f2e8c91d23'
down_revision: Union[str, None] = '798aa363dcb2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('users') as batch_op:
        batch_op.add_column(sa.Column('trial_started_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('trial_expires_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('users') as batch_op:
        batch_op.drop_column('trial_expires_at')
        batch_op.drop_column('trial_started_at')
