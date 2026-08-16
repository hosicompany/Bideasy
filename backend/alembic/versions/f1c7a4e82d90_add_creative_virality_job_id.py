"""add independent virality predictor job id

Revision ID: f1c7a4e82d90
Revises: e4b8c2d91f60
Create Date: 2026-08-14

영상 생성 job과 완성본 Virality Predictor job을 분리해 기록한다. 기존
attempt는 null을 유지하는 추가형 마이그레이션이다.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f1c7a4e82d90"
down_revision: Union[str, None] = "e4b8c2d91f60"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "creative_attempts",
        sa.Column("virality_job_id", sa.String(length=160), nullable=True),
    )
    op.create_index(
        "ix_creative_attempts_virality_job_id",
        "creative_attempts",
        ["virality_job_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_creative_attempts_virality_job_id",
        table_name="creative_attempts",
    )
    op.drop_column("creative_attempts", "virality_job_id")
