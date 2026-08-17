"""add creative attribution, growth events, and message validation

Revision ID: e4b8c2d91f60
Revises: d2f6a9c41b70
Create Date: 2026-08-14

기존 사용자·리드 행은 모두 null로 유지하는 추가형 마이그레이션이다.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e4b8c2d91f60"
down_revision: Union[str, None] = "d2f6a9c41b70"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # SQLite cannot add foreign keys with ALTER TABLE. batch_alter_table emits
    # ordinary ALTER statements on PostgreSQL and safely rebuilds only these two
    # existing tables on SQLite, preserving the project's local DB workflow.
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column("signup_content", sa.String(length=160), nullable=True))
        batch_op.add_column(sa.Column("signup_creative_id", sa.String(length=36), nullable=True))
        batch_op.create_foreign_key(
            "fk_users_signup_creative_id",
            "creative_briefs",
            ["signup_creative_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index("ix_users_signup_creative_id", ["signup_creative_id"])

    with op.batch_alter_table("leads") as batch_op:
        batch_op.add_column(sa.Column("utm_content", sa.String(length=160), nullable=True))
        batch_op.add_column(sa.Column("creative_id", sa.String(length=36), nullable=True))
        batch_op.create_foreign_key(
            "fk_leads_creative_id",
            "creative_briefs",
            ["creative_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index("ix_leads_creative_id", ["creative_id"])

    op.create_table(
        "growth_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_name", sa.String(length=60), nullable=False),
        sa.Column("dedupe_key", sa.String(length=220), nullable=True),
        sa.Column("anonymous_id", sa.String(length=80), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("lead_id", sa.Integer(), nullable=True),
        sa.Column("creative_id", sa.String(length=36), nullable=True),
        sa.Column("bid_no", sa.String(length=100), nullable=True),
        sa.Column("utm_source", sa.String(length=120), nullable=True),
        sa.Column("utm_medium", sa.String(length=120), nullable=True),
        sa.Column("utm_campaign", sa.String(length=160), nullable=True),
        sa.Column("utm_content", sa.String(length=160), nullable=True),
        sa.Column("event_metadata_json", sa.JSON(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["creative_id"], ["creative_briefs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dedupe_key"),
    )
    op.create_index("ix_growth_events_id", "growth_events", ["id"])
    op.create_index("ix_growth_events_event_name", "growth_events", ["event_name"])
    op.create_index("ix_growth_events_dedupe_key", "growth_events", ["dedupe_key"])
    op.create_index("ix_growth_events_anonymous_id", "growth_events", ["anonymous_id"])
    op.create_index("ix_growth_events_user_id", "growth_events", ["user_id"])
    op.create_index("ix_growth_events_lead_id", "growth_events", ["lead_id"])
    op.create_index("ix_growth_events_creative_id", "growth_events", ["creative_id"])
    op.create_index("ix_growth_events_bid_no", "growth_events", ["bid_no"])
    op.create_index("ix_growth_events_occurred_at", "growth_events", ["occurred_at"])

    op.create_table(
        "message_test_participants",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("participant_token", sa.String(length=80), nullable=False),
        sa.Column("campaign_key", sa.String(length=120), nullable=False),
        sa.Column("cohort_key", sa.String(length=32), nullable=False),
        sa.Column("variant", sa.String(length=1), nullable=False),
        sa.Column("industry", sa.String(length=40), nullable=False),
        sa.Column("staff_count", sa.Integer(), nullable=False),
        sa.Column("directly_handles_bids", sa.Boolean(), nullable=False),
        sa.Column("monthly_notice_reviews", sa.Integer(), nullable=False),
        sa.Column("exposure_ms", sa.Integer(), nullable=True),
        sa.Column("service_understanding", sa.Text(), nullable=True),
        sa.Column("usage_moment", sa.Text(), nullable=True),
        sa.Column("checked_items", sa.Text(), nullable=True),
        sa.Column("trust_score", sa.Integer(), nullable=True),
        sa.Column("relevance_score", sa.Integer(), nullable=True),
        sa.Column("coding_json", sa.JSON(), nullable=True),
        sa.Column("codes_hit", sa.Integer(), nullable=True),
        sa.Column("prediction_misunderstood", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("assigned_at", sa.DateTime(), nullable=False),
        sa.Column("submitted_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("participant_token"),
    )
    op.create_index("ix_message_test_participants_id", "message_test_participants", ["id"])
    op.create_index("ix_message_test_participants_participant_token", "message_test_participants", ["participant_token"])
    op.create_index("ix_message_test_participants_campaign_key", "message_test_participants", ["campaign_key"])
    op.create_index("ix_message_test_participants_cohort_key", "message_test_participants", ["cohort_key"])
    op.create_index("ix_message_test_participants_variant", "message_test_participants", ["variant"])
    op.create_index("ix_message_test_participants_assigned_at", "message_test_participants", ["assigned_at"])
    op.create_index("ix_message_test_participants_submitted_at", "message_test_participants", ["submitted_at"])
    op.create_index(
        "ix_message_test_campaign_variant",
        "message_test_participants",
        ["campaign_key", "variant"],
    )


def downgrade() -> None:
    op.drop_index("ix_message_test_campaign_variant", table_name="message_test_participants")
    op.drop_index("ix_message_test_participants_submitted_at", table_name="message_test_participants")
    op.drop_index("ix_message_test_participants_assigned_at", table_name="message_test_participants")
    op.drop_index("ix_message_test_participants_variant", table_name="message_test_participants")
    op.drop_index("ix_message_test_participants_cohort_key", table_name="message_test_participants")
    op.drop_index("ix_message_test_participants_campaign_key", table_name="message_test_participants")
    op.drop_index("ix_message_test_participants_participant_token", table_name="message_test_participants")
    op.drop_index("ix_message_test_participants_id", table_name="message_test_participants")
    op.drop_table("message_test_participants")

    op.drop_index("ix_growth_events_occurred_at", table_name="growth_events")
    op.drop_index("ix_growth_events_bid_no", table_name="growth_events")
    op.drop_index("ix_growth_events_creative_id", table_name="growth_events")
    op.drop_index("ix_growth_events_lead_id", table_name="growth_events")
    op.drop_index("ix_growth_events_user_id", table_name="growth_events")
    op.drop_index("ix_growth_events_anonymous_id", table_name="growth_events")
    op.drop_index("ix_growth_events_dedupe_key", table_name="growth_events")
    op.drop_index("ix_growth_events_event_name", table_name="growth_events")
    op.drop_index("ix_growth_events_id", table_name="growth_events")
    op.drop_table("growth_events")

    with op.batch_alter_table("leads") as batch_op:
        batch_op.drop_index("ix_leads_creative_id")
        batch_op.drop_constraint("fk_leads_creative_id", type_="foreignkey")
        batch_op.drop_column("creative_id")
        batch_op.drop_column("utm_content")

    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_index("ix_users_signup_creative_id")
        batch_op.drop_constraint("fk_users_signup_creative_id", type_="foreignkey")
        batch_op.drop_column("signup_creative_id")
        batch_op.drop_column("signup_content")
