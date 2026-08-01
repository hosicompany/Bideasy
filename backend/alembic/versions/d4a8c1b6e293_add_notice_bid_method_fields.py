"""add notice 낙찰자결정방법·하한율·예가수 필드

Revision ID: d4a8c1b6e293
Revises: e6b3d0c5a419
Create Date: 2026-08-02 00:00:00.000000

공고 목록 API 가 이미 주고 있었으나 크롤러가 읽지 않던 값들을 저장한다.

배경(2026-08-02 프로덕션 실측): `_map_item` 이 존재하지 않는 키를 읽어
공사 공고 3,511건의 bid_method·contract_method·region 이 **100% 결측**이었다.
그 결과 `recommend_bid_price(bid_method=)` 가 전 건 DEFAULT 전략으로 떨어져,
벤치마크에서 검증한 적격심사제 파라미터가 운영에서 한 번도 쓰이지 않았다.

추가 전용(nullable) — 기존 행은 NULL 로 남고, 재크롤 시 upsert 로 채워진다.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd4a8c1b6e293'
down_revision: Union[str, None] = 'e6b3d0c5a419'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_COLUMNS = (
    # sucsfbidMthdNm 원문 — 세부 기준(A값 감액 적용 등)은 여기에만 남는다
    ('bid_method_detail', sa.String(length=300)),
    ('bid_method_code', sa.String(length=20)),
    # sucsfbidLwltRate — 공고가 명시한 낙찰하한율(금액대 테이블 추정보다 우선)
    ('lower_limit_rate', sa.Float()),
    # totPrdprcNum / drwtPrdprcNum — 복수예비가격 총수·추첨수
    ('prdprc_total', sa.Integer()),
    ('prdprc_draw', sa.Integer()),
    ('bid_submit_method', sa.String(length=50)),
    ('notice_kind', sa.String(length=50)),
    ('re_notice_yn', sa.String(length=10)),
)


def upgrade() -> None:
    for name, coltype in _COLUMNS:
        op.add_column('notices', sa.Column(name, coltype, nullable=True))


def downgrade() -> None:
    for name, _ in reversed(_COLUMNS):
        op.drop_column('notices', name)
