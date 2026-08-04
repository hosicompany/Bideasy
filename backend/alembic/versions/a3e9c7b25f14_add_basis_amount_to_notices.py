"""notices 에 기초금액·A값 출처 컬럼 추가

`basic_price` 는 `presmptPrce`(추정가격, 부가세 제외)이지 기초금액이 아니다.
목록 API 는 기초금액을 주지 않고, 전용 오퍼레이션
`getBidPblancListInfoCnstwkBsisAmount` 가 `bssamt` 로 준다.

⛔ `basic_price` 를 갱신하는 마이그레이션이 아니다. 커버리지가 80% 라 확인된
건만 덮으면 한 컬럼에 또 두 기준이 섞인다 — 그게 이번 사고의 원인이다.
확인된 건만 `basis_amount` 에 넣고, 없으면 NULL 로 두어 소비 쪽에서
"기초금액 미확인"으로 다룬다. 경위: docs/PRICE_BASE_DEFECT.md

같은 응답이 A값 구성요소도 주므로 `a_value_source`(tier0) 와
`a_value_applicable`(bidPrceCalclAYn) 를 함께 둔다. N 이면 A값 0 이 정상이라,
결측과 구분해야 계산기가 "A값을 못 찾았다"고 잘못 말하지 않는다.

Revision ID: a3e9c7b25f14
Revises: c2f7a5e91d80
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a3e9c7b25f14"
down_revision: Union[str, None] = "c2f7a5e91d80"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_COLS = (
    ("basis_amount", sa.Float()),
    ("basis_amount_at", sa.DateTime()),
    ("prdprc_range_bgn", sa.Float()),
    ("prdprc_range_end", sa.Float()),
    ("a_value_source", sa.String(length=10)),
    ("a_value_applicable", sa.String(length=10)),
)


def upgrade() -> None:
    for name, type_ in _COLS:
        op.add_column("notices", sa.Column(name, type_, nullable=True))


def downgrade() -> None:
    for name, _ in reversed(_COLS):
        op.drop_column("notices", name)
