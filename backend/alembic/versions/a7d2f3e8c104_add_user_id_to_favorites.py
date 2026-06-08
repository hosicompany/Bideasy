"""add user_id to favorites

Revision ID: a7d2f3e8c104
Revises: f1c8d4a73b29
Create Date: 2026-06-08 13:00:00.000000

관심공고(favorites)를 사용자별로 분리. 기존엔 user_id 가 없어 전 사용자가
하나의 관심목록을 공유하던 버그 → user_id 추가로 격리.
기존 행은 NULL (어떤 사용자 조회에도 안 잡힘). 무중단 ADD COLUMN.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a7d2f3e8c104'
down_revision: Union[str, None] = 'f1c8d4a73b29'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('favorites', sa.Column('user_id', sa.Integer(), nullable=True))
    op.create_index('ix_favorites_user_id', 'favorites', ['user_id'])
    # SQLite 는 ALTER 로 FK 추가 불가 (테스트는 create_all 로 FK 포함 생성).
    # prod(PostgreSQL)에서만 FK 제약 추가.
    if op.get_bind().dialect.name != 'sqlite':
        op.create_foreign_key(
            'fk_favorites_user_id', 'favorites', 'users', ['user_id'], ['id']
        )


def downgrade() -> None:
    if op.get_bind().dialect.name != 'sqlite':
        op.drop_constraint('fk_favorites_user_id', 'favorites', type_='foreignkey')
    op.drop_index('ix_favorites_user_id', table_name='favorites')
    op.drop_column('favorites', 'user_id')
