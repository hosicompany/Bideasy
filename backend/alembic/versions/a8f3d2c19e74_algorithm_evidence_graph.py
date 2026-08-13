"""Algorithm evidence and outcome provenance graph.

Revision ID: a8f3d2c19e74
Revises: c9a4e7b13f28
Create Date: 2026-08-13
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "a8f3d2c19e74"
down_revision: Union[str, None] = "c9a4e7b13f28"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("mock_bids", sa.Column("a_value_status", sa.String(20)))

    op.create_table(
        "raw_source_snapshots",
        sa.Column("snapshot_hash", sa.String(64), primary_key=True),
        sa.Column("source_type", sa.String(40), nullable=False),
        sa.Column("source_uri", sa.String(500)),
        sa.Column("captured_at", sa.DateTime(), nullable=False),
        sa.Column("as_of_cutoff", sa.DateTime(), nullable=False),
        sa.Column("artifact_hash", sa.String(64), nullable=False),
        sa.Column("raw_payload", sa.JSON()),
        sa.Column("attributes", sa.JSON()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_raw_source_snapshots_source_type", "raw_source_snapshots", ["source_type"])
    op.create_index("ix_raw_source_snapshots_captured_at", "raw_source_snapshots", ["captured_at"])
    op.create_index("ix_raw_source_snapshots_as_of_cutoff", "raw_source_snapshots", ["as_of_cutoff"])

    op.create_table(
        "notice_revisions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("bid_no", sa.String(100), nullable=False),
        sa.Column("source_snapshot_hash", sa.String(64), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("supersedes_revision_id", sa.String(64)),
        sa.Column("effective_at", sa.DateTime(), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["source_snapshot_hash"], ["raw_source_snapshots.snapshot_hash"]),
        sa.ForeignKeyConstraint(["supersedes_revision_id"], ["notice_revisions.id"]),
        sa.UniqueConstraint("bid_no", "content_hash", name="uq_notice_revision_content"),
    )
    op.create_index("ix_notice_revisions_bid_no", "notice_revisions", ["bid_no"])
    op.create_index("ix_notice_revisions_effective_at", "notice_revisions", ["effective_at"])

    op.create_table(
        "opening_result_revisions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("bid_no", sa.String(100), nullable=False),
        sa.Column("revision_no", sa.Integer(), nullable=False),
        sa.Column("source_snapshot_hash", sa.String(64), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("supersedes_revision_id", sa.String(64)),
        sa.Column("observed_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["bid_no"], ["opening_results.bid_no"]),
        sa.ForeignKeyConstraint(
            ["source_snapshot_hash"], ["raw_source_snapshots.snapshot_hash"]
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_revision_id"], ["opening_result_revisions.id"]
        ),
        sa.UniqueConstraint(
            "bid_no", "revision_no", name="uq_opening_result_revision_number"
        ),
    )
    op.create_index(
        "ix_opening_result_revisions_bid_no", "opening_result_revisions", ["bid_no"]
    )
    op.create_index(
        "ix_opening_result_revisions_content_hash",
        "opening_result_revisions",
        ["content_hash"],
    )
    op.create_index(
        "ix_opening_result_revisions_observed_at",
        "opening_result_revisions",
        ["observed_at"],
    )

    op.create_table(
        "dataset_manifests",
        sa.Column("manifest_hash", sa.String(64), primary_key=True),
        sa.Column("as_of_cutoff", sa.DateTime(), nullable=False),
        sa.Column("code_sha", sa.String(64), nullable=False),
        sa.Column("formula_hash", sa.String(64), nullable=False),
        sa.Column("feature_version", sa.String(80), nullable=False),
        sa.Column("source_snapshot_hashes", sa.JSON(), nullable=False),
        sa.Column("population", sa.JSON(), nullable=False),
        sa.Column("filters", sa.JSON(), nullable=False),
        sa.Column("exclusions", sa.JSON(), nullable=False),
        sa.Column("distinct_notice_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_dataset_manifests_as_of_cutoff", "dataset_manifests", ["as_of_cutoff"])

    op.create_table(
        "experiment_manifests",
        sa.Column("experiment_id", sa.String(64), primary_key=True),
        sa.Column("as_of_cutoff", sa.DateTime(), nullable=False),
        sa.Column("data_manifest_hash", sa.String(64), nullable=False),
        sa.Column("code_sha", sa.String(64), nullable=False),
        sa.Column("formula_hash", sa.String(64), nullable=False),
        sa.Column("route", sa.String(32), nullable=False),
        sa.Column("feature_whitelist", sa.JSON(), nullable=False),
        sa.Column("temporal_folds", sa.JSON(), nullable=False),
        sa.Column("baselines", sa.JSON(), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("minimum_practical_effect", sa.JSON(), nullable=False),
        sa.Column("stop_rules", sa.JSON(), nullable=False),
        sa.Column("approval_id", sa.String(120)),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["data_manifest_hash"], ["dataset_manifests.manifest_hash"]),
    )
    op.create_index("ix_experiment_manifests_as_of_cutoff", "experiment_manifests", ["as_of_cutoff"])
    op.create_index("ix_experiment_manifests_route", "experiment_manifests", ["route"])
    op.create_index("ix_experiment_manifests_status", "experiment_manifests", ["status"])

    op.create_table(
        "strategy_candidates",
        sa.Column("candidate_id", sa.String(64), primary_key=True),
        sa.Column("strategy_version", sa.String(80), nullable=False),
        sa.Column("route", sa.String(32), nullable=False),
        sa.Column("parent_candidate_id", sa.String(64)),
        sa.Column("experiment_id", sa.String(64), nullable=False),
        sa.Column("data_manifest_hash", sa.String(64), nullable=False),
        sa.Column("code_sha", sa.String(64), nullable=False),
        sa.Column("formula_hash", sa.String(64), nullable=False),
        sa.Column("parameters_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["parent_candidate_id"], ["strategy_candidates.candidate_id"]),
        sa.ForeignKeyConstraint(["experiment_id"], ["experiment_manifests.experiment_id"]),
        sa.ForeignKeyConstraint(["data_manifest_hash"], ["dataset_manifests.manifest_hash"]),
        sa.UniqueConstraint("route", "strategy_version", name="uq_strategy_route_version"),
    )
    op.create_index("ix_strategy_candidates_route", "strategy_candidates", ["route"])
    op.create_index("ix_strategy_candidates_status", "strategy_candidates", ["status"])

    op.create_table(
        "algorithm_eval_runs",
        sa.Column("eval_run_id", sa.String(64), primary_key=True),
        sa.Column("experiment_id", sa.String(64), nullable=False),
        sa.Column("candidate_id", sa.String(64), nullable=False),
        sa.Column("data_manifest_hash", sa.String(64), nullable=False),
        sa.Column("route", sa.String(32), nullable=False),
        sa.Column("fold_name", sa.String(32), nullable=False),
        sa.Column("predictions_hash", sa.String(64), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("distinct_notice_count", sa.Integer(), nullable=False),
        sa.Column("maker_group", sa.String(80), nullable=False),
        sa.Column("verifier_group", sa.String(80), nullable=False),
        sa.Column("verifier_decision", sa.String(20)),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("sealed_test_opened_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["experiment_id"], ["experiment_manifests.experiment_id"]),
        sa.ForeignKeyConstraint(["candidate_id"], ["strategy_candidates.candidate_id"]),
        sa.ForeignKeyConstraint(["data_manifest_hash"], ["dataset_manifests.manifest_hash"]),
    )
    op.create_index("ix_algorithm_eval_runs_route", "algorithm_eval_runs", ["route"])
    op.create_index("ix_algorithm_eval_runs_status", "algorithm_eval_runs", ["status"])

    op.create_table(
        "algorithm_gate_decisions",
        sa.Column("decision_id", sa.String(64), primary_key=True),
        sa.Column("eval_run_id", sa.String(64), nullable=False),
        sa.Column("gate_name", sa.String(20), nullable=False),
        sa.Column("decision", sa.String(12), nullable=False),
        sa.Column("reason", sa.JSON(), nullable=False),
        sa.Column("approval_id", sa.String(120)),
        sa.Column("decided_by", sa.String(120), nullable=False),
        sa.Column("decided_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["eval_run_id"], ["algorithm_eval_runs.eval_run_id"]),
        sa.UniqueConstraint("eval_run_id", "gate_name", name="uq_eval_gate_decision"),
    )
    op.create_index("ix_algorithm_gate_decisions_decision", "algorithm_gate_decisions", ["decision"])

    op.create_table(
        "algorithm_approvals",
        sa.Column("approval_id", sa.String(120), primary_key=True),
        sa.Column("scope", sa.String(24), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("route", sa.String(32), nullable=False),
        sa.Column("strategy_version", sa.String(80), nullable=False),
        sa.Column("approved_by", sa.String(120), nullable=False),
        sa.Column("approved_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_algorithm_approvals_scope", "algorithm_approvals", ["scope"])
    op.create_index("ix_algorithm_approvals_status", "algorithm_approvals", ["status"])
    op.create_index("ix_algorithm_approvals_route", "algorithm_approvals", ["route"])

    op.create_table(
        "algorithm_deployments",
        sa.Column("deployment_id", sa.String(64), primary_key=True),
        sa.Column("route", sa.String(32), nullable=False),
        sa.Column("strategy_version", sa.String(80), nullable=False),
        sa.Column("candidate_id", sa.String(64), nullable=False),
        sa.Column("gate_decision_id", sa.String(64), nullable=False),
        sa.Column("approval_id", sa.String(120), nullable=False),
        sa.Column("code_sha", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("deployed_at", sa.DateTime()),
        sa.Column("rolled_back_at", sa.DateTime()),
        sa.Column("rollback_of_id", sa.String(64)),
        sa.ForeignKeyConstraint(["approval_id"], ["algorithm_approvals.approval_id"]),
        sa.ForeignKeyConstraint(["candidate_id"], ["strategy_candidates.candidate_id"]),
        sa.ForeignKeyConstraint(["gate_decision_id"], ["algorithm_gate_decisions.decision_id"]),
        sa.ForeignKeyConstraint(["rollback_of_id"], ["algorithm_deployments.deployment_id"]),
        sa.UniqueConstraint("route", "strategy_version", name="uq_deployment_route_version"),
    )
    op.create_index("ix_algorithm_deployments_route", "algorithm_deployments", ["route"])
    op.create_index("ix_algorithm_deployments_status", "algorithm_deployments", ["status"])

    op.create_table(
        "recommendation_events",
        sa.Column("recommendation_id", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.Integer()),
        sa.Column("notice_id", sa.String(100), nullable=False),
        sa.Column("as_of", sa.DateTime(), nullable=False),
        sa.Column("route", sa.String(32), nullable=False),
        sa.Column("strategy_version", sa.String(80), nullable=False),
        sa.Column("data_manifest_hash", sa.String(64)),
        sa.Column("code_sha", sa.String(64), nullable=False),
        sa.Column("formula_hash", sa.String(64), nullable=False),
        sa.Column("public_input_snapshot", sa.JSON(), nullable=False),
        sa.Column("input_snapshot_hash", sa.String(64), nullable=False),
        sa.Column("policies", sa.JSON(), nullable=False),
        sa.Column("abstain_reason", sa.String(80)),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
    )
    op.create_index("ix_recommendation_events_user_id", "recommendation_events", ["user_id"])
    op.create_index("ix_recommendation_events_notice_id", "recommendation_events", ["notice_id"])
    op.create_index("ix_recommendation_events_as_of", "recommendation_events", ["as_of"])
    op.create_index("ix_recommendation_events_route", "recommendation_events", ["route"])

    op.create_table(
        "user_decision_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("idempotency_key", sa.String(120), nullable=False),
        sa.Column("recommendation_id", sa.String(64), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(24), nullable=False),
        sa.Column("selected_policy", sa.String(24)),
        sa.Column("submitted_price", sa.BigInteger()),
        sa.Column("opening_bid_no", sa.String(100)),
        sa.Column("event_details", sa.JSON()),
        sa.Column("central_training_opt_in", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["recommendation_id"], ["recommendation_events.recommendation_id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["opening_bid_no"], ["opening_results.bid_no"]),
    )
    op.create_index("ix_user_decision_events_id", "user_decision_events", ["id"])
    op.create_index(
        "ix_user_decision_events_idempotency_key",
        "user_decision_events",
        ["idempotency_key"],
        unique=True,
    )
    op.create_index("ix_user_decision_events_recommendation_id", "user_decision_events", ["recommendation_id"])
    op.create_index("ix_user_decision_events_user_id", "user_decision_events", ["user_id"])
    op.create_index("ix_user_decision_events_event_type", "user_decision_events", ["event_type"])
    op.create_index("ix_user_decision_events_opening_bid_no", "user_decision_events", ["opening_bid_no"])
    op.create_index("ix_user_decision_events_occurred_at", "user_decision_events", ["occurred_at"])

    op.create_table(
        "competitor_observations",
        sa.Column("observation_id", sa.String(64), primary_key=True),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("plan_tier", sa.String(80)),
        sa.Column("notice_id", sa.String(100), nullable=False),
        sa.Column("as_of_cutoff", sa.DateTime(), nullable=False),
        sa.Column("observed_at", sa.DateTime(), nullable=False),
        sa.Column("deadline_at", sa.DateTime(), nullable=False),
        sa.Column("recommendation_price", sa.BigInteger()),
        sa.Column("recommendation_low", sa.BigInteger()),
        sa.Column("recommendation_high", sa.BigInteger()),
        sa.Column("confidence", sa.Float()),
        sa.Column("abstain_reason", sa.String(100)),
        sa.Column("artifact_hash", sa.String(64), nullable=False),
        sa.Column("artifact_uri", sa.String(500), nullable=False),
        sa.Column("terms_scope", sa.String(300), nullable=False),
        sa.Column("comparison_eligible", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("exclusion_reason", sa.String(120)),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "provider", "notice_id", "as_of_cutoff", "observed_at",
            name="uq_competitor_observation_cutoff",
        ),
    )
    op.create_index("ix_competitor_observations_provider", "competitor_observations", ["provider"])
    op.create_index("ix_competitor_observations_notice_id", "competitor_observations", ["notice_id"])
    op.create_index("ix_competitor_observations_as_of_cutoff", "competitor_observations", ["as_of_cutoff"])
    op.create_index("ix_competitor_observations_comparison_eligible", "competitor_observations", ["comparison_eligible"])


def downgrade() -> None:
    for table in (
        "competitor_observations",
        "user_decision_events",
        "recommendation_events",
        "algorithm_deployments",
        "algorithm_approvals",
        "algorithm_gate_decisions",
        "algorithm_eval_runs",
        "strategy_candidates",
        "experiment_manifests",
        "dataset_manifests",
        "opening_result_revisions",
        "notice_revisions",
        "raw_source_snapshots",
    ):
        op.drop_table(table)
    op.drop_column("mock_bids", "a_value_status")
