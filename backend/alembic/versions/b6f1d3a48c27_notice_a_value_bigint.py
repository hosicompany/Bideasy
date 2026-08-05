"""notices.a_value / net_cost 를 BigInteger 로

A값은 대형 공사에서 int4 상한(2,147,483,647)을 넘는다. 실측: 기초금액 298억
공고의 A값이 2,168,128,646 이었고, 이 한 건 때문에 기초금액 수집 배치가
NumericValueOutOfRange 로 죽어 **그날치 커밋이 통째로 롤백**됐다
(2026-08-05). `MockBid.price` 에서 겪은 것과 같은 함정이다.

`net_cost`(순공사원가)도 같은 이유로 함께 넓힌다.

Revision ID: b6f1d3a48c27
Revises: a3e9c7b25f14
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b6f1d3a48c27"
down_revision: Union[str, None] = "a3e9c7b25f14"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for col in ("a_value", "net_cost"):
        op.alter_column("notices", col,
                        existing_type=sa.Integer(), type_=sa.BigInteger(),
                        existing_nullable=True)


def downgrade() -> None:
    # ⚠️ 축소는 int4 를 넘는 값이 있으면 실패한다 — 그 편이 조용한 절단보다 낫다.
    for col in ("a_value", "net_cost"):
        op.alter_column("notices", col,
                        existing_type=sa.BigInteger(), type_=sa.Integer(),
                        existing_nullable=True)
