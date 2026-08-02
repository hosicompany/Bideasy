"""mock_bids.price / snapshot_a_value 를 BigInteger 로

Revision ID: b9d2f4a71c60
Revises: a7e3f9c25b18
Create Date: 2026-08-02 00:00:00.000000

공사 기초금액은 실측 최대 6,203억이다. Integer(int4, 21.4억)로는 대형 공고의
투찰가를 담지 못해 등록이 NumericValueOutOfRange 로 죽는다(실측: 기초금액
43억 공고의 투찰가 38.9억). 진행중 공고 중 기초금액 20억 초과가 221건이라
2시간 창에서도 곧 터지는 문제였다.

테이블이 비어 있는 시점의 타입 변경이라 데이터 손실 없음.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b9d2f4a71c60'
down_revision: Union[str, None] = 'a7e3f9c25b18'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column('mock_bids', 'price',
                    existing_type=sa.Integer(), type_=sa.BigInteger(),
                    existing_nullable=False)
    op.alter_column('mock_bids', 'snapshot_a_value',
                    existing_type=sa.Integer(), type_=sa.BigInteger(),
                    existing_nullable=True)


def downgrade() -> None:
    op.alter_column('mock_bids', 'snapshot_a_value',
                    existing_type=sa.BigInteger(), type_=sa.Integer(),
                    existing_nullable=True)
    op.alter_column('mock_bids', 'price',
                    existing_type=sa.BigInteger(), type_=sa.Integer(),
                    existing_nullable=False)
