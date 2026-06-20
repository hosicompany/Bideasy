"""add signup attribution columns to users (유입 채널 귀속)

Revision ID: c4f8a1e7d602
Revises: a3c7e1f9b204
Create Date: 2026-06-20 00:00:00.000000

가입 시점 first-touch 유입 채널(utm_source/medium/campaign + referrer)을 저장해
"어느 채널이 가입·결제를 데려오나"를 우리 데이터로 직접 집계하기 위한 컬럼.
외부 분석도구·쿠키 동의 없이 채널→가입→매출 귀속이 가능하다.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c4f8a1e7d602'
down_revision: Union[str, None] = 'a3c7e1f9b204'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('signup_source', sa.String(length=120), nullable=True))
    op.add_column('users', sa.Column('signup_medium', sa.String(length=120), nullable=True))
    op.add_column('users', sa.Column('signup_campaign', sa.String(length=160), nullable=True))
    op.add_column('users', sa.Column('signup_referrer', sa.String(length=300), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'signup_referrer')
    op.drop_column('users', 'signup_campaign')
    op.drop_column('users', 'signup_medium')
    op.drop_column('users', 'signup_source')
