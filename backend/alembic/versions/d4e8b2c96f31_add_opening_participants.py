"""opening_participants — 개찰 참가자 (모의투찰 등록 공고 한정)

Revision ID: d4e8b2c96f31
Revises: b9d2f4a71c60
Create Date: 2026-08-02 00:00:00.000000

개찰 API 는 참가자 전원의 순위(opengRank)·투찰가(bidprcAmt)를 주지만 기존
크롤러는 낙찰자 행만 남기고 버렸다. 이 테이블이 있어야 "우리가 몇 등이었는지"
(MOCK_BIDDING_DESIGN.md §4-3)를 재구성할 수 있다.

- 저장 범위는 mock_bids 에 등록된 공고만(설계 §P4 — 전수는 하루 169k행 함정).
- bid_price 는 BigInteger — 공사 기초금액 실측 최대 6,203억, int4 로는 죽는다.
- (bid_no, rank) 를 UNIQUE 로 걸지 않았다: API 가 동가 참가자에게 동순위를 줄
  가능성을 배제할 수 없어, 비유니크 인덱스 + 공고 단위 삭제-재삽입으로 중복을 막는다.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd4e8b2c96f31'
down_revision: Union[str, None] = 'b9d2f4a71c60'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'opening_participants',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('bid_no', sa.String(length=100), nullable=False),
        sa.Column('rank', sa.Integer(), nullable=True),
        sa.Column('company', sa.String(length=255), nullable=True),
        sa.Column('bid_price', sa.BigInteger(), nullable=True),
        sa.Column('bid_rate', sa.Float(), nullable=True),
        sa.Column('sucsf_yn', sa.String(length=5), nullable=True),
        sa.Column('crawled_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_opening_participants_id', 'opening_participants', ['id'])
    op.create_index('ix_opening_participants_bid_no', 'opening_participants', ['bid_no'])
    op.create_index('ix_opening_participants_bid_no_rank', 'opening_participants', ['bid_no', 'rank'])


def downgrade() -> None:
    op.drop_index('ix_opening_participants_bid_no_rank', table_name='opening_participants')
    op.drop_index('ix_opening_participants_bid_no', table_name='opening_participants')
    op.drop_index('ix_opening_participants_id', table_name='opening_participants')
    op.drop_table('opening_participants')
