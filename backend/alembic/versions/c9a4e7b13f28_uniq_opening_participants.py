"""normalize company + unique (bid_no, company, bid_price) on opening_participants

참가자 저장이 삭제-재삽입에서 **병합**으로 바뀌면서, 키가 갈리면 옛 행과 새 행이
둘 다 남는다. 삭제 경로가 코드에 없으므로 그 오염은 **영구**다. 진입 경로가 둘:

1. 상호 앞뒤 공백 — 파서에서 `.strip()` 으로 막았고, 여기서 기존 행도 정규화한다
   (실측 2026-08-12: 212행 / 466,850).
2. 동시 실행 — beat 런과 어드민 수동 트리거가 겹치면 두 워커가 같은 스냅샷을 보고
   양쪽 다 INSERT 한다. 애플리케이션 레벨로는 막을 수 없어 **DB 제약**에 맡긴다.

실측상 새 키 기준 중복은 0건이라 제약을 바로 걸 수 있다. 그래도 정규화가 중복을
만들 수 있으므로(공백 있는 행과 없는 행이 같은 키가 된다) 제약 생성 전에 정리한다.

Revision ID: c9a4e7b13f28
Revises: 6c034544c26d
Create Date: 2026-08-12
"""
from typing import Sequence, Union

from alembic import op

revision: str = 'c9a4e7b13f28'
down_revision: Union[str, None] = '6c034544c26d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

INDEX = 'uq_opening_participants_bid_company_price'


def upgrade() -> None:
    bind = op.get_bind()
    # 1) 상호 정규화 — 파서와 같은 규칙(앞뒤 공백 제거).
    #    `TRIM` 은 표준 SQL 이라 PostgreSQL·SQLite 둘 다 동작한다.
    bind.exec_driver_sql(
        "UPDATE opening_participants SET company = TRIM(company) "
        "WHERE company IS NOT NULL AND company <> TRIM(company)"
    )
    # 2) 정규화로 생겼을 수 있는 중복 정리 — 같은 키에서 가장 오래된 행만 남긴다.
    #    `DELETE ... USING` 은 PostgreSQL 전용이라 서브쿼리로 쓴다(격리 검증 가능).
    bind.exec_driver_sql(
        """
        DELETE FROM opening_participants
        WHERE id NOT IN (
            SELECT MIN(id) FROM opening_participants
            GROUP BY bid_no, company, bid_price
        )
        """
    )
    # 3) 동시 INSERT 를 DB 가 막는다
    op.create_index(INDEX, 'opening_participants',
                    ['bid_no', 'company', 'bid_price'], unique=True)


def downgrade() -> None:
    op.drop_index(INDEX, table_name='opening_participants')
