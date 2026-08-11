"""add valid_participants_count to mock_bid_results

등수의 분모를 **유효 투찰자 수**로 따로 센다.

개찰 API 는 낙찰하한선 이상 유효 투찰자에게만 `opengRank` 를 준다(2026-08-11
운영 실측: 참가자 462,900행 중 47.6%가 무효라 순위 없음). 종전 등수는 무효
투찰까지 세어 평균 15.79 부풀어 있었다. 등수를 유효 기준으로 고치면서,
전 참가자 수(`participants_count` = 경쟁 강도)와 등수의 분모를 분리한다.

기존 행은 NULL 로 남고, `backfill_participant_ranks` 가 값이 달라진 건을
새 scoring_rev 로 다시 계산한다(원장 행은 수정하지 않는다 — 설계 §0.5-3).

Revision ID: a3f9d2c47e61
Revises: 6c034544c26d
Create Date: 2026-08-11
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'a3f9d2c47e61'
down_revision: Union[str, None] = '6c034544c26d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('mock_bid_results',
                  sa.Column('valid_participants_count', sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column('mock_bid_results', 'valid_participants_count')
