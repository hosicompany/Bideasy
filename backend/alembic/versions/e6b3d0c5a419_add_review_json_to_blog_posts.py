"""add review_json to blog_posts (자동 검수 게이트 — 그림자 모드)

콘텐츠 엔진 Phase 1. 초안 검수 판정(PASS/WARN/FAIL + 검사 내역)을 저장한다.
그림자 모드라 발행 경로는 불변 — 판정과 사람 행동의 일치율을 모으는 것이 목적.

Revision ID: e6b3d0c5a419
Revises: c8e5b1f37d94
Create Date: 2026-08-01
"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "e6b3d0c5a419"
down_revision = "c8e5b1f37d94"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("blog_posts", sa.Column("review_json", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("blog_posts", "review_json")
