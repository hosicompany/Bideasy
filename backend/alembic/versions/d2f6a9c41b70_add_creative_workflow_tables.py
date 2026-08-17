"""add Higgsfield creative workflow tables

Revision ID: d2f6a9c41b70
Revises: c9a4e7b13f28
Create Date: 2026-08-14

크리에이티브 brief 수정 이력과 Higgsfield 실행 결과를 분리한다.
brief는 현재 정본, attempt/output은 이전 결과를 덮어쓰지 않는
append-only 원장이다. 기존 테이블을 갱신하지 않는 추가 전용 마이그레이션.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d2f6a9c41b70"
down_revision: Union[str, None] = "c9a4e7b13f28"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "creative_briefs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("source_type", sa.String(length=30), server_default="manual", nullable=False),
        sa.Column("source_ref_id", sa.String(length=120), nullable=True),
        sa.Column("source_hash", sa.String(length=64), nullable=True),
        sa.Column("campaign_key", sa.String(length=120), nullable=False),
        sa.Column("concept_key", sa.String(length=80), nullable=False),
        sa.Column("variant", sa.String(length=20), server_default="A", nullable=False),
        sa.Column("channel", sa.String(length=40), nullable=False),
        sa.Column("format", sa.String(length=40), nullable=False),
        sa.Column("hook", sa.String(length=500), nullable=False),
        sa.Column("body_copy", sa.Text(), server_default="", nullable=False),
        sa.Column("cta_copy", sa.String(length=200), nullable=False),
        sa.Column("landing_path", sa.String(length=500), nullable=False),
        sa.Column("utm_source", sa.String(length=120), nullable=True),
        sa.Column("utm_medium", sa.String(length=120), nullable=True),
        sa.Column("utm_campaign", sa.String(length=160), nullable=True),
        sa.Column("generation_spec_json", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("status", sa.String(length=30), server_default="DRAFT", nullable=False),
        sa.Column("approved_by", sa.Integer(), nullable=True),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["approved_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_creative_briefs_source_type", "creative_briefs", ["source_type"])
    op.create_index("ix_creative_briefs_source_ref_id", "creative_briefs", ["source_ref_id"])
    op.create_index("ix_creative_briefs_campaign_key", "creative_briefs", ["campaign_key"])
    op.create_index("ix_creative_briefs_concept_key", "creative_briefs", ["concept_key"])
    op.create_index("ix_creative_briefs_status", "creative_briefs", ["status"])
    op.create_index("ix_creative_briefs_created_at", "creative_briefs", ["created_at"])

    op.create_table(
        "creative_attempts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("creative_id", sa.String(length=36), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("runner_id", sa.String(length=120), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(), nullable=True),
        sa.Column("cli_version", sa.String(length=30), nullable=True),
        sa.Column("job_type", sa.String(length=60), nullable=False),
        sa.Column("prompt", sa.Text(), server_default="", nullable=False),
        sa.Column("params_json", sa.JSON(), nullable=False),
        sa.Column("input_files_json", sa.JSON(), nullable=False),
        sa.Column("prompt_sha256", sa.String(length=64), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("higgsfield_job_id", sa.String(length=160), nullable=True),
        sa.Column("status", sa.String(length=30), server_default="QUEUED", nullable=False),
        sa.Column("error", sa.String(length=1000), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["creative_id"], ["creative_briefs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("creative_id", "attempt_no", name="uq_creative_attempt_number"),
    )
    op.create_index("ix_creative_attempts_id", "creative_attempts", ["id"])
    op.create_index("ix_creative_attempts_creative_id", "creative_attempts", ["creative_id"])
    op.create_index("ix_creative_attempts_runner_id", "creative_attempts", ["runner_id"])
    op.create_index("ix_creative_attempts_lease_expires_at", "creative_attempts", ["lease_expires_at"])
    op.create_index("ix_creative_attempts_input_hash", "creative_attempts", ["input_hash"])
    op.create_index("ix_creative_attempts_higgsfield_job_id", "creative_attempts", ["higgsfield_job_id"])
    op.create_index("ix_creative_attempts_status", "creative_attempts", ["status"])
    op.create_index("ix_creative_attempts_created_at", "creative_attempts", ["created_at"])
    op.create_index("ix_creative_attempt_queue", "creative_attempts", ["status", "created_at"])

    op.create_table(
        "creative_outputs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("attempt_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("storage_path", sa.String(length=700), nullable=False),
        sa.Column("public_url", sa.String(length=700), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("mime_type", sa.String(length=100), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("review_json", sa.JSON(), nullable=True),
        sa.Column("virality_json", sa.JSON(), nullable=True),
        sa.Column("is_primary", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["attempt_id"], ["creative_attempts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("attempt_id", "kind", "sha256", name="uq_creative_output_content"),
    )
    op.create_index("ix_creative_outputs_id", "creative_outputs", ["id"])
    op.create_index("ix_creative_outputs_attempt_id", "creative_outputs", ["attempt_id"])
    op.create_index("ix_creative_outputs_kind", "creative_outputs", ["kind"])
    op.create_index("ix_creative_outputs_sha256", "creative_outputs", ["sha256"])
    op.create_index("ix_creative_outputs_created_at", "creative_outputs", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_creative_outputs_created_at", table_name="creative_outputs")
    op.drop_index("ix_creative_outputs_sha256", table_name="creative_outputs")
    op.drop_index("ix_creative_outputs_kind", table_name="creative_outputs")
    op.drop_index("ix_creative_outputs_attempt_id", table_name="creative_outputs")
    op.drop_index("ix_creative_outputs_id", table_name="creative_outputs")
    op.drop_table("creative_outputs")

    op.drop_index("ix_creative_attempt_queue", table_name="creative_attempts")
    op.drop_index("ix_creative_attempts_created_at", table_name="creative_attempts")
    op.drop_index("ix_creative_attempts_status", table_name="creative_attempts")
    op.drop_index("ix_creative_attempts_higgsfield_job_id", table_name="creative_attempts")
    op.drop_index("ix_creative_attempts_input_hash", table_name="creative_attempts")
    op.drop_index("ix_creative_attempts_lease_expires_at", table_name="creative_attempts")
    op.drop_index("ix_creative_attempts_runner_id", table_name="creative_attempts")
    op.drop_index("ix_creative_attempts_creative_id", table_name="creative_attempts")
    op.drop_index("ix_creative_attempts_id", table_name="creative_attempts")
    op.drop_table("creative_attempts")

    op.drop_index("ix_creative_briefs_created_at", table_name="creative_briefs")
    op.drop_index("ix_creative_briefs_status", table_name="creative_briefs")
    op.drop_index("ix_creative_briefs_concept_key", table_name="creative_briefs")
    op.drop_index("ix_creative_briefs_campaign_key", table_name="creative_briefs")
    op.drop_index("ix_creative_briefs_source_ref_id", table_name="creative_briefs")
    op.drop_index("ix_creative_briefs_source_type", table_name="creative_briefs")
    op.drop_table("creative_briefs")
