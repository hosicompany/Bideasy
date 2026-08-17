"""add private creative input assets

Revision ID: a6d9c3e71b42
Revises: f1c7a4e82d90
Create Date: 2026-08-15

관리자가 업로드한 source UI, storyboard, voiceover, reference 원본을
공개 creative output과 분리해 기록한다. 기존 행은 변경하지 않는 추가형
마이그레이션이다.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a6d9c3e71b42"
down_revision: Union[str, None] = "f1c7a4e82d90"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "creative_input_assets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("creative_id", sa.String(length=36), nullable=False),
        sa.Column("role", sa.String(length=30), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("storage_path", sa.String(length=700), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("mime_type", sa.String(length=100), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("media_metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["creative_id"], ["creative_briefs.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "storage_path", name="uq_creative_input_asset_storage_path"
        ),
    )
    op.create_index(
        "ix_creative_input_assets_id", "creative_input_assets", ["id"]
    )
    op.create_index(
        "ix_creative_input_assets_creative_id",
        "creative_input_assets",
        ["creative_id"],
    )
    op.create_index(
        "ix_creative_input_assets_role", "creative_input_assets", ["role"]
    )
    op.create_index(
        "ix_creative_input_assets_sha256", "creative_input_assets", ["sha256"]
    )
    op.create_index(
        "ix_creative_input_assets_created_at",
        "creative_input_assets",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_creative_input_assets_created_at", table_name="creative_input_assets"
    )
    op.drop_index(
        "ix_creative_input_assets_sha256", table_name="creative_input_assets"
    )
    op.drop_index(
        "ix_creative_input_assets_role", table_name="creative_input_assets"
    )
    op.drop_index(
        "ix_creative_input_assets_creative_id", table_name="creative_input_assets"
    )
    op.drop_index(
        "ix_creative_input_assets_id", table_name="creative_input_assets"
    )
    op.drop_table("creative_input_assets")
