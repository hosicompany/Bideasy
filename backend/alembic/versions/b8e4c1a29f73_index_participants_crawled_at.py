"""index opening_participants.crawled_at

`rank_axis_health` 가 최근 크롤분을 표본으로 뽑을 때 쓴다(시간창 7일).
없으면 어드민 화면을 열 때마다 참가자 전 행을 훑는다 — 현재 46만 행이고
보존기간 정책이 없어 계속 증가한다.

⚠️ 별도 리비전으로 둔 이유: 앞 리비전(`a3f9d2c47e61`)은 이미 푸시돼 다른
환경에서 적용됐을 수 있다. alembic 은 리비전 파일의 체크섬을 보지 않으므로,
적용된 리비전에 DDL 을 덧붙이면 그 환경에서는 **조용히 건너뛴다**(에러도 없이
인덱스만 없는 상태가 남는다).

Revision ID: b8e4c1a29f73
Revises: a3f9d2c47e61
Create Date: 2026-08-12
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'b8e4c1a29f73'
down_revision: Union[str, None] = 'a3f9d2c47e61'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


INDEX = 'ix_opening_participants_crawled_at'
TABLE = 'opening_participants'


def _has_index() -> bool:
    return INDEX in {ix['name'] for ix
                     in sa.inspect(op.get_bind()).get_indexes(TABLE)}


def upgrade() -> None:
    # 존재 확인 후 생성 — 분할 이전 판본(`a3f9d2c47e61` 에 인덱스가 들어 있던
    # 버전)을 이미 적용한 로컬/스테이징 DB 에서 DuplicateTable 로 배포가 죽는다.
    if not _has_index():
        op.create_index(INDEX, TABLE, ['crawled_at'])


def downgrade() -> None:
    if _has_index():
        op.drop_index(INDEX, table_name=TABLE)
