"""initial schema

Revision ID: 8c517d3e3d3a
Revises:
Create Date: 2026-02-20 11:01:15.988841

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8c517d3e3d3a'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = inspector.get_table_names()

    # --- Full CREATE for fresh databases (PostgreSQL) ---
    if "users" not in existing_tables:
        op.create_table(
            "users",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("email", sa.String(255), unique=True, nullable=False, index=True),
            sa.Column("hashed_password", sa.String(255), nullable=False),
            sa.Column("company_name", sa.String(255), server_default="Hosi Company"),
            sa.Column("ceo_name", sa.String(100)),
            sa.Column("licenses", sa.Text()),
            sa.Column("location", sa.String(100)),
            sa.Column("capacity_cost", sa.Integer(), server_default="0"),
            sa.Column("performance_record", sa.Integer(), server_default="0"),
            sa.Column("points", sa.Integer(), server_default="0"),
        )

    if "notices" not in existing_tables:
        op.create_table(
            "notices",
            sa.Column("bid_no", sa.String(100), primary_key=True, index=True),
            sa.Column("title", sa.String(500), index=True),
            sa.Column("content", sa.Text()),
            sa.Column("basic_price", sa.Float()),
            sa.Column("contract_type", sa.String(50), server_default="CONSTRUCTION"),
            sa.Column("start_date", sa.DateTime()),
            sa.Column("end_date", sa.DateTime()),
            sa.Column("organization", sa.String(255)),
            sa.Column("demand_organization", sa.String(255)),
            sa.Column("bid_method", sa.String(100)),
            sa.Column("contract_method", sa.String(100)),
            sa.Column("bid_type", sa.String(100)),
            sa.Column("status", sa.String(50)),
            sa.Column("region", sa.String(100)),
            sa.Column("budget_amount", sa.Float()),
            sa.Column("opening_date", sa.String(100)),
            sa.Column("international_bid", sa.String(10)),
            sa.Column("joint_contract", sa.String(10)),
            sa.Column("sme_only", sa.String(10)),
            sa.Column("big_company_ok", sa.String(10)),
            sa.Column("bid_qualification", sa.String(255)),
            sa.Column("emergency_bid", sa.String(10)),
            sa.Column("rebid_yn", sa.String(10)),
            sa.Column("attachment_url", sa.String(500)),
            sa.Column("attachment_name", sa.String(255)),
            sa.Column("a_value", sa.Integer(), server_default="0"),
            sa.Column("net_cost", sa.Integer(), server_default="0"),
        )

    if "user_bids" not in existing_tables:
        op.create_table(
            "user_bids",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id")),
            sa.Column("notice_id", sa.String(100), sa.ForeignKey("notices.bid_no")),
            sa.Column("bid_price", sa.Integer()),
            sa.Column("rate", sa.Float()),
            sa.Column("created_at", sa.DateTime()),
        )

    if "opening_results" not in existing_tables:
        op.create_table(
            "opening_results",
            sa.Column("bid_no", sa.String(100), primary_key=True, index=True),
            sa.Column("organization", sa.String(255), index=True),
            sa.Column("region", sa.String(100), index=True),
            sa.Column("open_date", sa.DateTime(), index=True),
            sa.Column("basic_price", sa.Float()),
            sa.Column("reserved_price", sa.Float()),
            sa.Column("bid_method", sa.String(100)),
            sa.Column("winner_company", sa.String(255)),
            sa.Column("winner_price", sa.Float()),
            sa.Column("winner_rate", sa.Float()),
            sa.Column("participants_count", sa.Integer()),
            sa.Column("crawled_at", sa.DateTime()),
        )

    if "ai_analysis_logs" not in existing_tables:
        op.create_table(
            "ai_analysis_logs",
            sa.Column("bid_no", sa.String(100), sa.ForeignKey("notices.bid_no"), primary_key=True),
            sa.Column("summary_json", sa.JSON()),
            sa.Column("risk_factors", sa.JSON()),
            sa.Column("llm_model", sa.String(50), server_default="gpt-4o-mini"),
            sa.Column("token_usage", sa.Integer()),
            sa.Column("created_at", sa.DateTime()),
        )

    if "point_transactions" not in existing_tables:
        op.create_table(
            "point_transactions",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("amount", sa.Integer(), nullable=False),
            sa.Column("balance_after", sa.Integer(), nullable=False),
            sa.Column("tx_type", sa.String(50), nullable=False),
            sa.Column("description", sa.String(255)),
            sa.Column("bid_no", sa.String(100), sa.ForeignKey("notices.bid_no")),
            sa.Column("created_at", sa.DateTime()),
        )

    if "favorites" not in existing_tables:
        op.create_table(
            "favorites",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("bid_no", sa.String(100), sa.ForeignKey("notices.bid_no"), nullable=False),
            sa.Column("created_at", sa.DateTime()),
        )

    # --- Patch existing SQLite DBs (tables exist but columns may be missing) ---
    if "users" in existing_tables:
        existing_cols = {c["name"] for c in inspector.get_columns("users")}
        with op.batch_alter_table("users") as batch_op:
            if "ceo_name" not in existing_cols:
                batch_op.add_column(sa.Column("ceo_name", sa.String(100)))
            if "licenses" not in existing_cols:
                batch_op.add_column(sa.Column("licenses", sa.Text()))
            if "location" not in existing_cols:
                batch_op.add_column(sa.Column("location", sa.String(100)))
            if "capacity_cost" not in existing_cols:
                batch_op.add_column(sa.Column("capacity_cost", sa.Integer(), server_default="0"))
            if "performance_record" not in existing_cols:
                batch_op.add_column(sa.Column("performance_record", sa.Integer(), server_default="0"))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("favorites")
    op.drop_table("point_transactions")
    op.drop_table("ai_analysis_logs")
    op.drop_table("opening_results")
    op.drop_table("user_bids")
    op.drop_table("notices")
    op.drop_table("users")
