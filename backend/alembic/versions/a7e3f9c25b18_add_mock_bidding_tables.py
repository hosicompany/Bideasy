"""add mock_bids / mock_bid_results (모의투찰 사전 등록·채점)

Revision ID: a7e3f9c25b18
Revises: d4a8c1b6e293
Create Date: 2026-08-02 00:00:00.000000

설계·게이트 정본: docs/MOCK_BIDDING_DESIGN.md (구현 착수 전 동결)

mock_bids 는 **불변(append-only)** 이다. 마감 전에 확정한 투찰가를 못 박아,
자가보정이 파라미터를 갱신해도 과거 추천가가 소급 변경되지 않게 한다.
재채점은 mock_bid_results 에 새 행(scoring_rev)으로 쌓는다.

추가 전용 — 기존 테이블 무영향.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a7e3f9c25b18'
down_revision: Union[str, None] = 'd4a8c1b6e293'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'mock_bids',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('bid_no', sa.String(length=100), nullable=False),
        sa.Column('arm', sa.String(length=30), nullable=False),
        sa.Column('registered_at', sa.DateTime(), nullable=False),
        sa.Column('deadline_at', sa.DateTime(), nullable=False),
        sa.Column('strategy_version', sa.String(length=40), nullable=True),
        sa.Column('code_rev', sa.String(length=40), nullable=True),
        sa.Column('price', sa.Integer(), nullable=False),
        sa.Column('bid_rate', sa.Float(), nullable=True),
        sa.Column('adjustment', sa.Float(), nullable=True),
        sa.Column('margin', sa.Float(), nullable=True),
        sa.Column('snapshot_basic_price', sa.Float(), nullable=False),
        sa.Column('snapshot_a_value', sa.Integer(), nullable=True),
        sa.Column('a_value_source', sa.String(length=10), nullable=True),
        sa.Column('snapshot_lower_limit_rate', sa.Float(), nullable=True),
        sa.Column('llr_source', sa.String(length=10), nullable=True),
        sa.Column('snapshot_bid_method', sa.String(length=100), nullable=True),
        sa.Column('snapshot_contract_type', sa.String(length=50), nullable=True),
        sa.Column('snapshot_notice_kind', sa.String(length=50), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('bid_no', 'arm', name='uq_mock_bids_bid_no_arm'),
    )
    op.create_index(op.f('ix_mock_bids_id'), 'mock_bids', ['id'])
    op.create_index(op.f('ix_mock_bids_bid_no'), 'mock_bids', ['bid_no'])
    op.create_index(op.f('ix_mock_bids_registered_at'), 'mock_bids', ['registered_at'])
    op.create_index(op.f('ix_mock_bids_status'), 'mock_bids', ['status'])

    op.create_table(
        'mock_bid_results',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('mock_bid_id', sa.Integer(), nullable=False),
        sa.Column('scoring_rev', sa.Integer(), nullable=False),
        sa.Column('outcome', sa.String(length=20), nullable=False),
        sa.Column('actual_reserved_price', sa.Float(), nullable=True),
        sa.Column('actual_winner_price', sa.Float(), nullable=True),
        sa.Column('actual_lower_limit', sa.Float(), nullable=True),
        sa.Column('estimated_rank', sa.Integer(), nullable=True),
        sa.Column('participants_count', sa.Integer(), nullable=True),
        sa.Column('gap_to_winner_pct', sa.Float(), nullable=True),
        sa.Column('gap_to_limit_pct', sa.Float(), nullable=True),
        sa.Column('reserved_ratio_actual', sa.Float(), nullable=True),
        sa.Column('reserved_ratio_predicted', sa.Float(), nullable=True),
        sa.Column('ratio_error', sa.Float(), nullable=True),
        sa.Column('failure_tags', sa.JSON(), nullable=True),
        sa.Column('scored_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['mock_bid_id'], ['mock_bids.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_mock_bid_results_id'), 'mock_bid_results', ['id'])
    op.create_index(op.f('ix_mock_bid_results_mock_bid_id'), 'mock_bid_results', ['mock_bid_id'])
    op.create_index(op.f('ix_mock_bid_results_outcome'), 'mock_bid_results', ['outcome'])
    op.create_index(op.f('ix_mock_bid_results_scored_at'), 'mock_bid_results', ['scored_at'])


def downgrade() -> None:
    op.drop_table('mock_bid_results')
    op.drop_table('mock_bids')
