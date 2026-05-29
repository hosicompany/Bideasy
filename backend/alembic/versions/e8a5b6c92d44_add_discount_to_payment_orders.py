"""add discount fields to payment_orders

Revision ID: e8a5b6c92d44
Revises: d7f1b9c34a82
Create Date: 2026-05-29 14:00:00.000000

첫 달 50% 할인(win-back) 적용 결과 추적:
- discount_amount: 적용된 할인 금액 (원)
- discount_reason: 할인 사유 코드 (예: TRIAL_WINBACK_50)

원금 복원: amount + discount_amount = 정가.
discount_reason 으로 어떤 캠페인이 효과 있었는지 admin 통계에서 분석.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e8a5b6c92d44'
down_revision: Union[str, None] = 'd7f1b9c34a82'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('payment_orders') as batch_op:
        batch_op.add_column(sa.Column('discount_amount', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('discount_reason', sa.String(50), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('payment_orders') as batch_op:
        batch_op.drop_column('discount_reason')
        batch_op.drop_column('discount_amount')
