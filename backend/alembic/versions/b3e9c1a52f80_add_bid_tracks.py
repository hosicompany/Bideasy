"""add bid_tracks (마감 추적)

Revision ID: b3e9c1a52f80
Revises: a7d2f3e8c104
Create Date: 2026-06-08 14:00:00.000000

마감 추적 테이블 — 사용자가 추적하는 공고. 마감 리마인더(deadline_tasks)용.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b3e9c1a52f80'
down_revision: Union[str, None] = 'a7d2f3e8c104'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'bid_tracks',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False, index=True),
        sa.Column('bid_no', sa.String(100), sa.ForeignKey('notices.bid_no'), nullable=False),
        sa.Column('remind', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table('bid_tracks')
