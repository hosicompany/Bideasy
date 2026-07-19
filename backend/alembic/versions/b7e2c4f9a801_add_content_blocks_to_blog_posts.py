"""add content blocks columns to blog_posts (콘텐츠 엔진 Phase 1)

구조화 정본(ContentSource) 블록 저장 — docs/CONTENT_ENGINE.md §2.
blocks_json 이 원본, body_md 는 블록에서 렌더된 파생.

Revision ID: b7e2c4f9a801
Revises: d9f3a1b7c204
Create Date: 2026-07-19
"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "b7e2c4f9a801"
down_revision = "d9f3a1b7c204"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("blog_posts", sa.Column("blocks_json", sa.JSON(), nullable=True))
    op.add_column("blog_posts", sa.Column("channel_assets_json", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("blog_posts", "channel_assets_json")
    op.drop_column("blog_posts", "blocks_json")
