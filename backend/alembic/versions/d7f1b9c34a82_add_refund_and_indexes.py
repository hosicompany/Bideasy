"""add refund fields, payment user_id nullable, and indexes

Revision ID: d7f1b9c34a82
Revises: c5e3a8d72f41
Create Date: 2026-05-28 11:05:00.000000

관리자 대시보드 Phase A — 결제 환불 추적 + 사용자 삭제 정책 변경.

## payment_orders 변경
- refund_amount (Integer, nullable) : 환불 금액 (부분 환불 지원 — 누적)
- refund_reason (String 500, nullable) : 환불 사유
- refunded_at (DateTime, nullable) : 환불 완료 시각 (idempotency 검사 키)
- refund_payment_key (String 200, nullable) : Toss 환불 응답의 paymentKey
- user_id : nullable=True 변경 (SET NULL 정책 — 사용자 삭제 후 회계 기록 보존)

## 인덱스 (대시보드 집계 성능)
- payment_orders(confirmed_at) : 일·주·월 매출 집계
- payment_orders(status) : PENDING 정리 쿼리
- users(tier) : tier 분포 도넛 차트
- users(trial_expires_at) : Trial 전환율 추적
- ai_analysis_logs(created_at) : AI 비용 일별 집계
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd7f1b9c34a82'
down_revision: Union[str, None] = 'c5e3a8d72f41'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # payment_orders 환불 필드 + user_id nullable
    with op.batch_alter_table('payment_orders') as batch_op:
        batch_op.add_column(sa.Column('refund_amount', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('refund_reason', sa.String(500), nullable=True))
        batch_op.add_column(sa.Column('refunded_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('refund_payment_key', sa.String(200), nullable=True))
        # user_id NOT NULL → nullable (SET NULL 정책)
        batch_op.alter_column('user_id', existing_type=sa.Integer(), nullable=True)
        batch_op.create_index('ix_payment_orders_confirmed_at', ['confirmed_at'])
        batch_op.create_index('ix_payment_orders_status', ['status'])

    # users 인덱스
    with op.batch_alter_table('users') as batch_op:
        batch_op.create_index('ix_users_tier', ['tier'])
        batch_op.create_index('ix_users_trial_expires_at', ['trial_expires_at'])

    # ai_analysis_logs 인덱스 (일별 비용 집계)
    with op.batch_alter_table('ai_analysis_logs') as batch_op:
        batch_op.create_index('ix_ai_analysis_logs_created_at', ['created_at'])


def downgrade() -> None:
    with op.batch_alter_table('ai_analysis_logs') as batch_op:
        batch_op.drop_index('ix_ai_analysis_logs_created_at')

    with op.batch_alter_table('users') as batch_op:
        batch_op.drop_index('ix_users_trial_expires_at')
        batch_op.drop_index('ix_users_tier')

    with op.batch_alter_table('payment_orders') as batch_op:
        batch_op.drop_index('ix_payment_orders_status')
        batch_op.drop_index('ix_payment_orders_confirmed_at')
        batch_op.alter_column('user_id', existing_type=sa.Integer(), nullable=False)
        batch_op.drop_column('refund_payment_key')
        batch_op.drop_column('refunded_at')
        batch_op.drop_column('refund_reason')
        batch_op.drop_column('refund_amount')
