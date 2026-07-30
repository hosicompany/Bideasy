"""add outbound_messages (아웃바운드 발송 원장 — 멱등·추적)

Revision ID: a9d3f5c17e42
Revises: f4c1e8a92b37
Create Date: 2026-07-30 00:00:00.000000

SES 발송 파이프라인의 원장. dedupe_key 유니크로 같은 메일의 중복 발송을 DB 차원에서
막고(재시도·중복 스케줄 방어), 동의 없음·수신거부로 **보내지 않은 건도** skipped 로
남겨 발송 게이트가 실제로 도는지 관측 가능하게 한다. 추가 전용 — 기존 데이터 무영향.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a9d3f5c17e42'
down_revision: Union[str, None] = 'f4c1e8a92b37'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'outbound_messages',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('subject_type', sa.String(length=10), nullable=False),
        sa.Column('subject_id', sa.Integer(), nullable=True),
        sa.Column('email', sa.String(length=255), nullable=True),
        sa.Column('channel', sa.String(length=20), nullable=False),
        sa.Column('template', sa.String(length=60), nullable=False),
        sa.Column('category', sa.String(length=20), nullable=False),
        sa.Column('subject', sa.String(length=200), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('reason', sa.String(length=60), nullable=True),
        sa.Column('provider', sa.String(length=20), nullable=True),
        sa.Column('provider_message_id', sa.String(length=120), nullable=True),
        sa.Column('error', sa.String(length=300), nullable=True),
        sa.Column('dedupe_key', sa.String(length=160), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_outbound_messages_id'), 'outbound_messages', ['id'], unique=False)
    op.create_index(op.f('ix_outbound_messages_subject_type'), 'outbound_messages', ['subject_type'], unique=False)
    op.create_index(op.f('ix_outbound_messages_subject_id'), 'outbound_messages', ['subject_id'], unique=False)
    op.create_index(op.f('ix_outbound_messages_email'), 'outbound_messages', ['email'], unique=False)
    op.create_index(op.f('ix_outbound_messages_created_at'), 'outbound_messages', ['created_at'], unique=False)
    # 멱등성의 핵심 — 같은 dedupe_key 는 한 번만 존재할 수 있다.
    op.create_index(op.f('ix_outbound_messages_dedupe_key'), 'outbound_messages', ['dedupe_key'], unique=True)


def downgrade() -> None:
    op.drop_index(op.f('ix_outbound_messages_dedupe_key'), table_name='outbound_messages')
    op.drop_index(op.f('ix_outbound_messages_created_at'), table_name='outbound_messages')
    op.drop_index(op.f('ix_outbound_messages_email'), table_name='outbound_messages')
    op.drop_index(op.f('ix_outbound_messages_subject_id'), table_name='outbound_messages')
    op.drop_index(op.f('ix_outbound_messages_subject_type'), table_name='outbound_messages')
    op.drop_index(op.f('ix_outbound_messages_id'), table_name='outbound_messages')
    op.drop_table('outbound_messages')
