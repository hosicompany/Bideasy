"""누적 개찰 통계 집계 테이블 (opening_stats)

개찰 원장을 전수로 쌓으면 공사만 하루 169k행이다. 사용자가 묻는 건 "이 기관
이 방식이면 보통 몇 %에서 낙찰되나" 한 줄이라, 축으로 묶어 분위수만 남긴다.
설계·비목표: docs/OPENING_STATS_DESIGN.md

UNIQUE 를 (organization, bid_method, amount_band) 로 잡되 기관 무관 집계는
NULL 이 아니라 빈 문자열을 쓴다 — Postgres 는 UNIQUE 에서 NULL 을 서로 다른
값으로 보므로 NULL 을 쓰면 중복 행이 조용히 쌓인다.

Revision ID: f7c4a2e18b53
Revises: b6f1d3a48c27
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f7c4a2e18b53"
down_revision: Union[str, None] = "b6f1d3a48c27"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "opening_stats",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization", sa.String(length=255), nullable=False,
                  server_default=""),
        sa.Column("bid_method", sa.String(length=100), nullable=False,
                  server_default=""),
        sa.Column("amount_band", sa.String(length=20), nullable=False,
                  server_default=""),
        sa.Column("n", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("period_start", sa.DateTime(), nullable=True),
        sa.Column("period_end", sa.DateTime(), nullable=True),
        sa.Column("winner_rate_p10", sa.Float(), nullable=True),
        sa.Column("winner_rate_p50", sa.Float(), nullable=True),
        sa.Column("winner_rate_p90", sa.Float(), nullable=True),
        sa.Column("reserved_ratio_p10", sa.Float(), nullable=True),
        sa.Column("reserved_ratio_p50", sa.Float(), nullable=True),
        sa.Column("reserved_ratio_p90", sa.Float(), nullable=True),
        sa.Column("participants_p50", sa.Integer(), nullable=True),
        sa.Column("participants_max", sa.Integer(), nullable=True),
        sa.Column("participants_n", sa.Integer(), nullable=True),
        sa.Column("computed_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization", "bid_method", "amount_band",
                            name="uq_opening_stats_axis"),
    )
    op.create_index("ix_opening_stats_id", "opening_stats", ["id"])
    op.create_index("ix_opening_stats_organization", "opening_stats",
                    ["organization"])
    op.create_index("ix_opening_stats_lookup", "opening_stats",
                    ["bid_method", "amount_band"])


def downgrade() -> None:
    op.drop_index("ix_opening_stats_lookup", table_name="opening_stats")
    op.drop_index("ix_opening_stats_organization", table_name="opening_stats")
    op.drop_index("ix_opening_stats_id", table_name="opening_stats")
    op.drop_table("opening_stats")
