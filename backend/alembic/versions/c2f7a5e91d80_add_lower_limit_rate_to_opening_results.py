"""opening_results 에 lower_limit_rate 추가

개찰 API 는 `sucsfLwstlmtRt`(낙찰하한율)를 레코드별로 준다. 그동안 이 값을
버리고 금액대 테이블로 역산했는데, 요율 개정(2026-01-30) 같은 변화가 있으면
테이블이 뒤처져 판정이 통째로 어긋난다. 공고가 명시한 값을 그대로 보관한다.

같은 배포에서 `basic_price` 의 출처도 `presmptPrce`(추정가격) → `bssAmt`
(기초금액)로 바뀐다. 기존 행은 별도 백필 스크립트로 정정한다
(`backend/scripts/backfill_opening_basis.py`) — 마이그레이션에서 하지 않는
이유는 API 재조회가 필요해 수 분이 걸리고, 실패 시 배포 전체를 막기 때문이다.

Revision ID: c2f7a5e91d80
Revises: d4e8b2c96f31
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c2f7a5e91d80"
down_revision: Union[str, None] = "d4e8b2c96f31"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "opening_results",
        sa.Column("lower_limit_rate", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("opening_results", "lower_limit_rate")
