"""add blog_posts table (DB 기반 런타임 발행)

Revision ID: e1a4c7b2f039
Revises: d5a2b8c14e90
Create Date: 2026-06-16 06:00:00.000000

마크다운 파일 블로그와 하이브리드. 자동 데이터스토리·관리자 즉석글을 배포 없이
런타임 발행하기 위한 테이블. 필드는 마크다운 post dict 와 동형.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e1a4c7b2f039'
down_revision: Union[str, None] = 'd5a2b8c14e90'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'blog_posts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('slug', sa.String(length=200), nullable=False),
        sa.Column('title', sa.String(length=300), nullable=False),
        sa.Column('summary', sa.Text(), nullable=True),
        sa.Column('category', sa.String(length=80), nullable=True),
        sa.Column('tags', sa.String(length=300), nullable=True),
        sa.Column('cover', sa.String(length=500), nullable=True),
        sa.Column('hero', sa.String(length=500), nullable=True),
        sa.Column('body_md', sa.Text(), nullable=False),
        sa.Column('body_html', sa.Text(), nullable=False),
        sa.Column('reading_time', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='draft'),
        sa.Column('source', sa.String(length=20), nullable=False, server_default='admin'),
        sa.Column('date', sa.String(length=10), nullable=True),
        sa.Column('publish_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_blog_posts_slug', 'blog_posts', ['slug'], unique=True)
    op.create_index('ix_blog_posts_status', 'blog_posts', ['status'])


def downgrade() -> None:
    op.drop_index('ix_blog_posts_status', table_name='blog_posts')
    op.drop_index('ix_blog_posts_slug', table_name='blog_posts')
    op.drop_table('blog_posts')
