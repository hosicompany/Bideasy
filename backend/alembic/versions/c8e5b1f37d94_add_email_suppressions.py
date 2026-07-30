"""add email_suppressions (반송·불만 자동 억제)

Revision ID: c8e5b1f37d94
Revises: a9d3f5c17e42
Create Date: 2026-07-30 00:00:00.000000

하드 반송·스팸 신고(complaint) 주소를 발송 대상에서 영구 제외하기 위한 목록.
AWS 는 반송률 5%·불만율 0.1% 초과 시 계정 발송을 정지시키며, 평판이 깎이면 광고뿐
아니라 거래 메일(결제·영수증)까지 도달하지 않는다. 추가 전용 — 기존 데이터 무영향.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c8e5b1f37d94'
down_revision: Union[str, None] = 'a9d3f5c17e42'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'email_suppressions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('reason', sa.String(length=20), nullable=False),
        sa.Column('subtype', sa.String(length=40), nullable=True),
        sa.Column('source', sa.String(length=20), nullable=False),
        sa.Column('detail', sa.String(length=300), nullable=True),
        sa.Column('event_count', sa.Integer(), server_default='1', nullable=False),
        sa.Column('last_event_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_email_suppressions_id'), 'email_suppressions', ['id'], unique=False)
    # 같은 주소가 두 번 들어가면 억제 판정이 갈린다 → 유니크로 못 박는다.
    op.create_index(op.f('ix_email_suppressions_email'), 'email_suppressions', ['email'], unique=True)
    op.create_index(op.f('ix_email_suppressions_created_at'), 'email_suppressions', ['created_at'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_email_suppressions_created_at'), table_name='email_suppressions')
    op.drop_index(op.f('ix_email_suppressions_email'), table_name='email_suppressions')
    op.drop_index(op.f('ix_email_suppressions_id'), table_name='email_suppressions')
    op.drop_table('email_suppressions')
