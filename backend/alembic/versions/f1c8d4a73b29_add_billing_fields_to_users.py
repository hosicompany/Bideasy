"""add billing fields to users

Revision ID: f1c8d4a73b29
Revises: e8a5b6c92d44
Create Date: 2026-06-01 10:00:00.000000

토스 자동결제(빌링) 지원 — 빌링키 저장 + 자동 갱신 플래그.
- billing_key: 토스 빌링키 (카드정보 암호화 값, 영구 보관)
- billing_customer_key: 빌링키 발급 시 사용한 customerKey (청구 시 필요)
- billing_card: 표시용 마스킹 카드정보 (예: "신한 ****1234")
- billing_cycle: 자동 갱신 주기 (monthly | annual)
- auto_renew: 자동 갱신 on/off (해지 시 false)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f1c8d4a73b29'
down_revision: Union[str, None] = 'e8a5b6c92d44'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 순수 ADD COLUMN — PostgreSQL·SQLite(3.35+) 모두 native 지원.
    # (users 는 컬럼이 많아 batch_alter_table 재생성 시 토폴로지 정렬 충돌 발생 →
    #  plain add_column 으로 테이블 재생성 회피)
    op.add_column('users', sa.Column('billing_key', sa.String(200), nullable=True))
    op.add_column('users', sa.Column('billing_customer_key', sa.String(100), nullable=True))
    op.add_column('users', sa.Column('billing_card', sa.String(80), nullable=True))
    op.add_column('users', sa.Column('billing_cycle', sa.String(20), nullable=True))
    op.add_column(
        'users',
        sa.Column('auto_renew', sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column('users', 'auto_renew')
    op.drop_column('users', 'billing_cycle')
    op.drop_column('users', 'billing_card')
    op.drop_column('users', 'billing_customer_key')
    op.drop_column('users', 'billing_key')
