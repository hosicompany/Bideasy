"""add leads table (무료 자격 진단 리드 캡처)

Revision ID: d9f3a1b7c204
Revises: c4f8a1e7d602
Create Date: 2026-07-08 00:00:00.000000

무료 자격 진단 리드 마그넷의 저장소. 비로그인 방문자가 남긴 연락처(이메일/휴대폰)
+ 진단 입력(업종·지역·면허·시공능력) + 진단 결과 스냅샷(matched_count) + 유입
귀속(UTM) + 육성 채널/상태. 추가 전용(신규 테이블) — 기존 데이터 무영향.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd9f3a1b7c204'
down_revision: Union[str, None] = 'c4f8a1e7d602'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'leads',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=True),
        sa.Column('phone', sa.String(length=30), nullable=True),
        sa.Column('industry', sa.String(length=60), nullable=True),
        sa.Column('licenses', sa.String(length=255), nullable=True),
        sa.Column('region', sa.String(length=100), nullable=True),
        sa.Column('capacity_cost', sa.Integer(), nullable=True),
        sa.Column('matched_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('utm_source', sa.String(length=120), nullable=True),
        sa.Column('utm_medium', sa.String(length=120), nullable=True),
        sa.Column('utm_campaign', sa.String(length=160), nullable=True),
        sa.Column('referrer', sa.String(length=300), nullable=True),
        sa.Column('nurture_channel', sa.String(length=20), nullable=True),
        sa.Column('nurture_status', sa.String(length=20), server_default='new', nullable=False),
        sa.Column('converted_user_id', sa.Integer(), nullable=True),
        sa.Column('source', sa.String(length=40), server_default='web_diagnose', nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_leads_id'), 'leads', ['id'], unique=False)
    op.create_index(op.f('ix_leads_email'), 'leads', ['email'], unique=False)
    op.create_index(op.f('ix_leads_created_at'), 'leads', ['created_at'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_leads_created_at'), table_name='leads')
    op.drop_index(op.f('ix_leads_email'), table_name='leads')
    op.drop_index(op.f('ix_leads_id'), table_name='leads')
    op.drop_table('leads')
