"""Deterministic evidence-ledger guards for algorithm decisions.

This module records provenance; it never submits a bid or changes the active
strategy.  Production activation remains a separate, explicitly approved
operation.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy.orm import Session

from app.db import models
from app.schemas.algorithm_evidence import (
    RecommendationDecisionContract,
    UserDecisionCreate,
)


_PRIVATE_INPUT_KEYS = {
    "actual_submitted_price",
    "company_cost",
    "company_margin",
    "cost_price",
    "target_margin",
    "tenant_cost",
}


def canonical_hash(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _finite_metric(metrics: dict, key: str) -> float:
    value = metrics.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"metric {key} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"metric {key} must be a finite number")
    return number


def _nonnegative_int_metric(metrics: dict, key: str) -> int:
    value = metrics.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"metric {key} must be a non-negative integer")
    return value


def _reject_private_snapshot_keys(snapshot: dict) -> None:
    present = sorted(_PRIVATE_INPUT_KEYS.intersection(snapshot))
    if present:
        raise ValueError(
            "tenant-private values are forbidden in public_input_snapshot: "
            + ", ".join(present)
        )


def record_recommendation(
    db: Session,
    contract: RecommendationDecisionContract,
    *,
    user_id: int | None,
) -> models.RecommendationEvent:
    """Append a recommendation idempotently with a content hash."""
    existing = db.get(models.RecommendationEvent, contract.recommendation_id)
    if existing is not None:
        return existing

    snapshot = contract.public_input_snapshot
    _reject_private_snapshot_keys(snapshot)
    row = models.RecommendationEvent(
        recommendation_id=contract.recommendation_id,
        user_id=user_id,
        notice_id=contract.notice_id,
        as_of=contract.as_of,
        route=contract.route.value,
        strategy_version=contract.strategy_version,
        data_manifest_hash=contract.data_manifest_hash,
        code_sha=contract.code_sha,
        formula_hash=contract.formula_hash,
        public_input_snapshot=snapshot,
        input_snapshot_hash=canonical_hash(snapshot),
        policies=[policy.model_dump(mode="json") for policy in contract.policies],
        abstain_reason=contract.abstain_reason,
        evidence=contract.evidence,
    )
    db.add(row)
    db.flush()
    return row


def record_user_decision(
    db: Session,
    *,
    recommendation_id: str,
    user_id: int,
    event: UserDecisionCreate,
) -> tuple[models.UserDecisionEvent, bool]:
    """Append one tenant-owned user decision; duplicate keys are idempotent."""
    duplicate = (
        db.query(models.UserDecisionEvent)
        .filter(models.UserDecisionEvent.idempotency_key == event.idempotency_key)
        .first()
    )
    if duplicate is not None:
        if duplicate.user_id != user_id or duplicate.recommendation_id != recommendation_id:
            raise PermissionError("idempotency key belongs to a different recommendation")
        return duplicate, True

    recommendation = db.get(models.RecommendationEvent, recommendation_id)
    if recommendation is None:
        raise LookupError("recommendation not found")
    if recommendation.user_id is not None and recommendation.user_id != user_id:
        raise PermissionError("recommendation belongs to a different user")

    occurred_at = event.occurred_at or datetime.now(timezone.utc)
    recommendation_as_of = recommendation.as_of
    if recommendation_as_of.tzinfo is None:
        recommendation_as_of = recommendation_as_of.replace(tzinfo=timezone.utc)
    if occurred_at.tzinfo is None:
        occurred_at = occurred_at.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    if occurred_at < recommendation_as_of:
        raise ValueError("decision event cannot predate the recommendation")
    if occurred_at > now + timedelta(minutes=5):
        raise ValueError("decision event cannot be in the future")

    opening_bid_no = None
    if event.event_type == "OUTCOME_LINKED":
        opening = db.get(models.OpeningResult, recommendation.notice_id)
        if opening is None:
            raise LookupError("opening result not found for recommendation")
        opening_bid_no = opening.bid_no

    row = models.UserDecisionEvent(
        idempotency_key=event.idempotency_key,
        recommendation_id=recommendation_id,
        user_id=user_id,
        event_type=event.event_type,
        selected_policy=event.selected_policy,
        submitted_price=event.submitted_price,
        opening_bid_no=opening_bid_no,
        event_details=event.details,
        central_training_opt_in=event.central_training_opt_in,
        occurred_at=occurred_at,
    )
    db.add(row)
    db.flush()
    return row, False


def create_deployment_evidence(
    db: Session,
    *,
    candidate_id: str,
    gate_decision_id: str,
    approval_id: str,
    code_sha: str,
) -> models.AlgorithmDeployment:
    """Create deployment evidence only after matching G-C PASS + human approval.

    This function intentionally does not modify the strategy store.  The
    promotion executor must commit this row and the active-pointer change in
    its own atomic/rollback-aware boundary.
    """
    if not approval_id.strip():
        raise ValueError("human approval_id is required")
    candidate = db.get(models.StrategyCandidate, candidate_id)
    if candidate is None:
        raise LookupError("strategy candidate not found")
    if candidate.status != "CANDIDATE":
        raise ValueError("only a CANDIDATE strategy can be prepared")
    experiment = db.get(models.ExperimentManifest, candidate.experiment_id)
    if experiment is None or experiment.status != "FROZEN":
        raise ValueError("deployment requires a FROZEN experiment manifest")
    dataset = db.get(models.DatasetManifest, candidate.data_manifest_hash)
    if dataset is None:
        raise LookupError("dataset manifest not found")
    lineage_values = {
        "experiment": (
            experiment.route,
            experiment.data_manifest_hash,
            experiment.code_sha,
            experiment.formula_hash,
        ),
        "candidate": (
            candidate.route,
            candidate.data_manifest_hash,
            candidate.code_sha,
            candidate.formula_hash,
        ),
        "dataset": (
            candidate.route,
            dataset.manifest_hash,
            dataset.code_sha,
            dataset.formula_hash,
        ),
    }
    if len(set(lineage_values.values())) != 1:
        raise ValueError("experiment, candidate, and dataset lineage differ")
    if experiment.approval_id and experiment.approval_id != approval_id:
        raise ValueError("approval_id does not match frozen experiment scope")

    approval = db.get(models.AlgorithmApproval, approval_id)
    if approval is None:
        raise LookupError("persisted human approval not found")
    now = datetime.now(timezone.utc)
    expires_at = approval.expires_at
    if expires_at is not None and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if (
        approval.scope != "PROMOTION"
        or approval.status != "APPROVED"
        or approval.route != candidate.route
        or approval.strategy_version != candidate.strategy_version
        or (expires_at is not None and expires_at <= now)
    ):
        raise ValueError("human approval is not active or is outside route/version scope")

    gate = db.get(models.AlgorithmGateDecision, gate_decision_id)
    if gate is None:
        raise LookupError("gate decision not found")
    if gate.decision != "PASS" or gate.gate_name != "G-C":
        raise ValueError("deployment requires a G-C PASS decision")
    if gate.approval_id != approval_id:
        raise ValueError("approval_id does not match gate decision")
    eval_run = db.get(models.AlgorithmEvalRun, gate.eval_run_id)
    if eval_run is None or eval_run.candidate_id != candidate_id:
        raise ValueError("gate decision does not belong to candidate")
    if (
        eval_run.status != "VERIFIED"
        or eval_run.verifier_decision != "PASS"
        or eval_run.maker_group == eval_run.verifier_group
    ):
        raise ValueError("deployment requires an independent verified evaluator PASS")
    if eval_run.fold_name != "sealed_test":
        raise ValueError("deployment requires the sealed_test evaluation")
    if eval_run.sealed_test_opened_at is None:
        raise ValueError("sealed_test evaluation was not opened")
    if (
        eval_run.experiment_id != candidate.experiment_id
        or eval_run.route != candidate.route
        or eval_run.data_manifest_hash != candidate.data_manifest_hash
    ):
        raise ValueError("evaluation lineage differs from candidate")
    passed_gate_runs: dict[str, models.AlgorithmEvalRun] = {}
    prerequisite_rows = (
        db.query(models.AlgorithmGateDecision, models.AlgorithmEvalRun)
        .join(
            models.AlgorithmEvalRun,
            models.AlgorithmGateDecision.eval_run_id
            == models.AlgorithmEvalRun.eval_run_id,
        )
        .filter(
            models.AlgorithmEvalRun.experiment_id == candidate.experiment_id,
            models.AlgorithmEvalRun.candidate_id == candidate.candidate_id,
            models.AlgorithmEvalRun.route == candidate.route,
            models.AlgorithmGateDecision.decision == "PASS",
        )
        .all()
    )
    for decision, prerequisite_run in prerequisite_rows:
        same_lineage = (
            prerequisite_run.data_manifest_hash == candidate.data_manifest_hash
            and prerequisite_run.status == "VERIFIED"
            and prerequisite_run.verifier_decision == "PASS"
            and prerequisite_run.maker_group != prerequisite_run.verifier_group
        )
        if same_lineage:
            passed_gate_runs[decision.gate_name] = prerequisite_run

    passed_gates = set(passed_gate_runs)
    missing_gates = {"G0", "G-A", "G-B", "G-C"} - passed_gates
    if missing_gates:
        raise ValueError(
            "deployment prerequisites missing: " + ", ".join(sorted(missing_gates))
        )
    if passed_gate_runs["G-C"].eval_run_id != eval_run.eval_run_id:
        raise ValueError("selected G-C gate is not the verified sealed evaluation")

    g0_metrics = passed_gate_runs["G0"].metrics or {}
    if g0_metrics.get("g0_truth_pass") is not True:
        raise ValueError("G0 truth/formula parity evidence is missing")

    g_a_metrics = passed_gate_runs["G-A"].metrics or {}
    if (
        _finite_metric(g_a_metrics, "g_a_valid_result_reach") < 0.60
        or g_a_metrics.get("g_a_due_cohort_healthy") is not True
        or g_a_metrics.get("g_a_crawler_healthy") is not True
    ):
        raise ValueError("G-A requires >=60% reach plus healthy due cohort and crawler")

    g_b_run = passed_gate_runs["G-B"]
    g_b_metrics = g_b_run.metrics or {}
    if candidate.route == "QUALIFICATION":
        minimum_notices = 400
    else:
        minimum_notices = int((experiment.stop_rules or {}).get("minimum_paired_notices", 0))
        if minimum_notices < 1:
            raise ValueError("non-qualification route requires preregistered power/sample size")
    clean_notices = _nonnegative_int_metric(
        g_b_metrics,
        "clean_distinct_notice_count",
    )
    if clean_notices < minimum_notices or g_b_run.distinct_notice_count < minimum_notices:
        raise ValueError(
            f"G-B requires at least {minimum_notices} clean distinct notices"
        )

    g_c_metrics = eval_run.metrics or {}
    practical_effects = [
        float(value)
        for value in (experiment.minimum_practical_effect or {}).values()
        if (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(float(value))
        )
    ]
    if not practical_effects:
        raise ValueError("G-C requires a preregistered minimum practical effect")
    paired_notices = _nonnegative_int_metric(
        g_c_metrics,
        "g_c_paired_distinct_notice_count",
    )
    champion_coverage = _finite_metric(g_c_metrics, "g_c_champion_coverage")
    challenger_coverage = _finite_metric(g_c_metrics, "g_c_challenger_coverage")
    coverage_margin = (experiment.stop_rules or {}).get(
        "coverage_noninferiority_margin",
        0.0,
    )
    if (
        isinstance(coverage_margin, bool)
        or not isinstance(coverage_margin, (int, float))
        or not math.isfinite(float(coverage_margin))
        or not 0 <= float(coverage_margin) <= 1
    ):
        raise ValueError("coverage noninferiority margin must be finite in [0, 1]")
    if (
        paired_notices < minimum_notices
        or eval_run.distinct_notice_count < minimum_notices
        or not 0 <= champion_coverage <= 1
        or not 0 <= challenger_coverage <= 1
        or challenger_coverage
        < champion_coverage - float(coverage_margin)
        or _finite_metric(g_c_metrics, "g_c_primary_effect_ci_lower")
        < max(practical_effects)
        or _finite_metric(
            g_c_metrics,
            "g_c_dropout_delta_one_sided_95_upper",
        )
        > 0
        or _nonnegative_int_metric(g_c_metrics, "legal_calculation_errors") != 0
        or _nonnegative_int_metric(g_c_metrics, "margin_constraint_violations")
        != 0
    ):
        raise ValueError("G-C paired effect, safety, or hard-constraint evidence failed")
    if candidate.code_sha != code_sha:
        raise ValueError("deployed code_sha differs from evaluated candidate")

    existing = (
        db.query(models.AlgorithmDeployment)
        .filter(
            models.AlgorithmDeployment.route == candidate.route,
            models.AlgorithmDeployment.strategy_version == candidate.strategy_version,
        )
        .first()
    )
    if existing is not None:
        return existing

    row = models.AlgorithmDeployment(
        deployment_id=str(uuid4()),
        route=candidate.route,
        strategy_version=candidate.strategy_version,
        candidate_id=candidate.candidate_id,
        gate_decision_id=gate.decision_id,
        approval_id=approval_id,
        code_sha=code_sha,
        status="PENDING_ACTIVATION",
    )
    db.add(row)
    db.flush()
    return row
