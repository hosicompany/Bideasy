"""add support chat tables (support_messages, support_tickets)

Revision ID: d5a2b8c14e90
Revises: c4f1a9e63b27
Create Date: 2026-06-11 05:30:00.000000

고객 챗봇: 대화 로그(자가학습 데이터) + 문의 티켓.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd5a2b8c14e90'
down_revision: Union[str, None] = 'c4f1a9e63b27'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'support_messages',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('session_id', sa.String(length=64), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('role', sa.String(length=16), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('resolved', sa.Boolean(), nullable=True),
        sa.Column('topic', sa.String(length=80), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_support_messages_session_id', 'support_messages', ['session_id'])
    op.create_index('ix_support_messages_user_id', 'support_messages', ['user_id'])
    op.create_index('ix_support_messages_created_at', 'support_messages', ['created_at'])

    op.create_table(
        'support_tickets',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('email', sa.String(length=255), nullable=True),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('session_id', sa.String(length=64), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_support_tickets_user_id', 'support_tickets', ['user_id'])
    op.create_index('ix_support_tickets_status', 'support_tickets', ['status'])
    op.create_index('ix_support_tickets_created_at', 'support_tickets', ['created_at'])


def downgrade() -> None:
    op.drop_table('support_tickets')
    op.drop_table('support_messages')
