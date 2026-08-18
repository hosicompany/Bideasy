"""Evidence graph invariants and recommendation outcome linkage."""

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.db import models
from app.schemas.algorithm_evidence import (
    CompetitorObservationContract,
    ExperimentManifestContract,
    RecommendationDecisionContract,
    RecommendationPolicy,
    UserDecisionCreate,
)
from app.services.algorithm_evidence import (
    canonical_hash,
    create_deployment_evidence,
    record_recommendation,
    record_user_decision,
)
from app.services.autocalibrate.strategy_store import (
    BOOTSTRAP_VERSION_ID,
    FileStrategyStore,
    StrategyVersion,
    strategy_parameters_hash,
)


HASH = "a" * 64
NOW = datetime.now(timezone.utc)


def _recommendation(*, recommendation_id="rec-1", user_id=1):
    return RecommendationDecisionContract(
        recommendation_id=recommendation_id,
        notice_id="N-1",
        as_of=NOW,
        route="QUALIFICATION",
        strategy_version="v1",
        data_manifest_hash=HASH,
        code_sha="abcdef1",
        formula_hash=HASH,
        public_input_snapshot={"basis_amount": 100_000_000, "bid_method": "적격심사제"},
        policies=[
            RecommendationPolicy(
                name="balanced",
                price=89_900_000,
                probability_unavailable_reason="calibration gate not passed",
            )
        ],
        evidence={"sample_size": 42, "calibrated": False},
    )


def test_manifest_requires_train_validation_and_sealed_test():
    with pytest.raises(ValidationError, match="sealed_test"):
        ExperimentManifestContract(
            experiment_id="exp-1",
            as_of_cutoff=NOW,
            data_manifest_hash=HASH,
            code_sha="abcdef1",
            formula_hash=HASH,
            route="QUALIFICATION",
            feature_whitelist=[],
            temporal_folds={"train": {}, "validation": {}},
            baselines=["active_champion"],
            metrics=["valid_price_reach"],
            minimum_practical_effect={"valid_price_reach": 0.01},
            stop_rules={"max_iterations": 3},
        )


def test_probability_null_requires_explicit_reason():
    with pytest.raises(ValidationError, match="probability_unavailable_reason"):
        RecommendationPolicy(name="balanced", price=10_000)


def test_recommendation_is_content_hashed_and_idempotent(db_session):
    contract = _recommendation()
    first = record_recommendation(db_session, contract, user_id=None)
    second = record_recommendation(db_session, contract, user_id=None)

    assert first is second
    assert first.input_snapshot_hash == canonical_hash(contract.public_input_snapshot)
    assert first.policies[0]["probability_unavailable_reason"]


@pytest.mark.parametrize(
    "private_key",
    ["company_cost", "target_margin", "actual_submitted_price"],
)
def test_tenant_private_values_cannot_enter_recommendation_snapshot(db_session, private_key):
    contract = _recommendation(recommendation_id=f"private-{private_key}")
    contract.public_input_snapshot[private_key] = 123

    with pytest.raises(ValueError, match="tenant-private"):
        record_recommendation(db_session, contract, user_id=None)


def test_user_decision_is_tenant_owned_and_idempotent(db_session):
    user = models.User(email="owner@example.com", hashed_password="x")
    other = models.User(email="other@example.com", hashed_password="x")
    db_session.add_all([user, other])
    db_session.flush()
    recommendation = record_recommendation(db_session, _recommendation(), user_id=user.id)
    event = UserDecisionCreate(
        idempotency_key="decision-key-001",
        event_type="SUBMITTED",
        submitted_price=89_900_000,
    )

    first, duplicate = record_user_decision(
        db_session,
        recommendation_id=recommendation.recommendation_id,
        user_id=user.id,
        event=event,
    )
    second, duplicate_again = record_user_decision(
        db_session,
        recommendation_id=recommendation.recommendation_id,
        user_id=user.id,
        event=event,
    )

    assert duplicate is False
    assert duplicate_again is True
    assert second.id == first.id
    with pytest.raises(PermissionError):
        record_user_decision(
            db_session,
            recommendation_id=recommendation.recommendation_id,
            user_id=other.id,
            event=event.model_copy(update={"idempotency_key": "decision-key-002"}),
        )


@pytest.mark.parametrize(
    "occurred_at",
    [NOW - timedelta(minutes=1), NOW + timedelta(days=1)],
)
def test_user_decision_rejects_impossible_event_time(db_session, occurred_at):
    user = models.User(email=f"event-{occurred_at.timestamp()}@example.com", hashed_password="x")
    db_session.add(user)
    db_session.flush()
    recommendation = record_recommendation(
        db_session,
        _recommendation(recommendation_id=f"event-{occurred_at.timestamp()}"),
        user_id=user.id,
    )

    with pytest.raises(ValueError, match="predate|future"):
        record_user_decision(
            db_session,
            recommendation_id=recommendation.recommendation_id,
            user_id=user.id,
            event=UserDecisionCreate(
                idempotency_key=f"impossible-{occurred_at.timestamp()}",
                event_type="EXPOSED",
                occurred_at=occurred_at,
            ),
        )


def test_outcome_event_links_authoritative_opening_result(db_session):
    user = models.User(email="outcome@example.com", hashed_password="x")
    db_session.add(user)
    db_session.flush()
    recommendation = record_recommendation(
        db_session,
        _recommendation(user_id=user.id),
        user_id=user.id,
    )
    event = UserDecisionCreate(
        idempotency_key="outcome-link-001",
        event_type="OUTCOME_LINKED",
    )

    with pytest.raises(LookupError, match="opening result"):
        record_user_decision(
            db_session,
            recommendation_id=recommendation.recommendation_id,
            user_id=user.id,
            event=event,
        )

    db_session.add(models.OpeningResult(
        bid_no="N-1",
        basic_price=100_000_000,
        reserved_price=100_500_000,
        winner_price=90_000_000,
    ))
    db_session.flush()
    linked, duplicate = record_user_decision(
        db_session,
        recommendation_id=recommendation.recommendation_id,
        user_id=user.id,
        event=event,
    )

    assert duplicate is False
    assert linked.opening_bid_no == "N-1"


def _seed_candidate_and_gate(db_session, *, decision="PASS", approval="APPROVE-1"):
    params = {"DEFAULT": {"small": [0.0, 1.0]}}
    dataset = models.DatasetManifest(
        manifest_hash=HASH,
        as_of_cutoff=NOW,
        code_sha="abcdef1",
        formula_hash=HASH,
        feature_version="v1",
        source_snapshot_hashes=[],
        population={},
        filters={},
        exclusions={},
        distinct_notice_count=400,
    )
    experiment = models.ExperimentManifest(
        experiment_id="exp-1",
        as_of_cutoff=NOW,
        data_manifest_hash=HASH,
        code_sha="abcdef1",
        formula_hash=HASH,
        route="QUALIFICATION",
        feature_whitelist=[],
        temporal_folds={},
        baselines=[],
        metrics=[],
        minimum_practical_effect={"primary_success": 0.01},
        stop_rules={
            "minimum_paired_notices": 400,
            "coverage_noninferiority_margin": 0.0,
        },
        approval_id=approval,
        status="FROZEN",
    )
    candidate = models.StrategyCandidate(
        candidate_id="candidate-1",
        strategy_version="v1",
        route="QUALIFICATION",
        experiment_id="exp-1",
        data_manifest_hash=HASH,
        code_sha="abcdef1",
        formula_hash=HASH,
        parameters_hash=strategy_parameters_hash(params),
    )
    eval_run = models.AlgorithmEvalRun(
        eval_run_id="eval-1",
        experiment_id="exp-1",
        candidate_id="candidate-1",
        data_manifest_hash=HASH,
        route="QUALIFICATION",
        fold_name="sealed_test",
        predictions_hash="c" * 64,
        metrics={
            "g0_truth_pass": True,
            "g_a_valid_result_reach": 0.60,
            "g_a_due_cohort_healthy": True,
            "g_a_crawler_healthy": True,
            "clean_distinct_notice_count": 400,
            "g_c_paired_distinct_notice_count": 400,
            "g_c_champion_coverage": 1.0,
            "g_c_challenger_coverage": 1.0,
            "g_c_primary_effect_ci_lower": 0.02,
            "g_c_dropout_delta_one_sided_95_upper": 0.0,
            "legal_calculation_errors": 0,
            "margin_constraint_violations": 0,
        },
        distinct_notice_count=400,
        maker_group="maker",
        verifier_group="verifier",
        verifier_decision="PASS",
        status="VERIFIED",
        sealed_test_opened_at=NOW,
    )
    approval_row = models.AlgorithmApproval(
        approval_id=approval,
        scope="PROMOTION",
        status="APPROVED",
        route="QUALIFICATION",
        strategy_version="v1",
        approved_by="human@example.com",
        approved_at=NOW,
    )
    gates = [
        models.AlgorithmGateDecision(
            decision_id=f"gate-{name}",
            eval_run_id="eval-1",
            gate_name=name,
            decision=decision if name == "G-C" else "PASS",
            reason={},
            approval_id=approval if name == "G-C" else None,
            decided_by="human@example.com",
        )
        for name in ("G0", "G-A", "G-B", "G-C")
    ]
    gate = gates[-1]
    db_session.add_all(
        [dataset, experiment, candidate, eval_run, approval_row, *gates]
    )
    db_session.flush()
    return candidate, gate, params


def test_deployment_requires_matching_pass_and_human_approval(db_session, tmp_path):
    candidate, gate, params = _seed_candidate_and_gate(db_session)

    with pytest.raises(ValueError, match="human approval"):
        create_deployment_evidence(
            db_session,
            candidate_id=candidate.candidate_id,
            gate_decision_id=gate.decision_id,
            approval_id="",
            code_sha=candidate.code_sha,
        )
    with pytest.raises(ValueError, match="does not match"):
        create_deployment_evidence(
            db_session,
            candidate_id=candidate.candidate_id,
            gate_decision_id=gate.decision_id,
            approval_id="WRONG",
            code_sha=candidate.code_sha,
        )

    deployment = create_deployment_evidence(
        db_session,
        candidate_id=candidate.candidate_id,
        gate_decision_id=gate.decision_id,
        approval_id="APPROVE-1",
        code_sha=candidate.code_sha,
    )
    assert deployment.status == "PENDING_ACTIVATION"


@pytest.mark.xfail(
    strict=True,
    reason=(
        "StrategyVersion.route/candidate 상태·FileStrategyStore.save_candidate·prepare_strategy_promotion 은 "
        "62bb01a(자가보정 승격 게이트) 가 추가하는 것 — R1 과 양립 불가한 목적함수 재설계와 묶여 분리 병합 대상. "
        "자가보정 존폐 결정(pm/AUTOCALIBRATE_DECISION_2026-08-18.md §5-②) 과 함께 후속. "
        "이 PR 에서는 prepare_strategy_promotion 자체를 뺐다(dead code)."
    ),
)
def test_strategy_promotion_from_file_candidate(db_session, tmp_path):
    candidate, gate, params = _seed_candidate_and_gate(db_session)
    from app.services.algorithm_evidence import prepare_strategy_promotion  # noqa: F401 — 62bb01a 후 복원

    version = StrategyVersion(
        version_id=candidate.strategy_version,
        created_at="2026-08-13T00:00:00",
        params=params,
        status="candidate",
        parent_version=BOOTSTRAP_VERSION_ID,
        route="QUALIFICATION",
    )
    store = FileStrategyStore(tmp_path / "strategy")
    store.ensure_bootstrap({"DEFAULT": {"small": [-0.3, 1.0]}})
    store.save_candidate(version)
    prepared = prepare_strategy_promotion(
        db_session,
        version=store.get(version.version_id),
        candidate_id=candidate.candidate_id,
        gate_decision_id=gate.decision_id,
        approval_id="APPROVE-1",
        code_sha=candidate.code_sha,
    )
    assert prepared.deployment_id  # 62bb01a 복원 시 해피패스 테스트의 deployment 와 대조로 되돌릴 것
    assert prepared.status == "PENDING_ACTIVATION"
    assert store.load_active().version_id == BOOTSTRAP_VERSION_ID
    assert not hasattr(store, "_commit_authorized")


def test_deployment_requires_all_route_gates(db_session):
    candidate, gate, _params = _seed_candidate_and_gate(db_session)
    g_b = (
        db_session.query(models.AlgorithmGateDecision)
        .filter_by(eval_run_id="eval-1", gate_name="G-B")
        .one()
    )
    db_session.delete(g_b)
    db_session.flush()

    with pytest.raises(ValueError, match="G-B"):
        create_deployment_evidence(
            db_session,
            candidate_id=candidate.candidate_id,
            gate_decision_id=gate.decision_id,
            approval_id="APPROVE-1",
            code_sha=candidate.code_sha,
        )


def test_deployment_requires_persisted_route_version_scoped_approval(db_session):
    candidate, gate, _params = _seed_candidate_and_gate(db_session)
    approval = db_session.get(models.AlgorithmApproval, "APPROVE-1")
    approval.route = "PRICE_DOMINANT"
    db_session.flush()

    with pytest.raises(ValueError, match="outside route/version scope"):
        create_deployment_evidence(
            db_session,
            candidate_id=candidate.candidate_id,
            gate_decision_id=gate.decision_id,
            approval_id="APPROVE-1",
            code_sha=candidate.code_sha,
        )


def test_deployment_rejects_formula_lineage_skew(db_session):
    candidate, gate, _params = _seed_candidate_and_gate(db_session)
    dataset = db_session.get(models.DatasetManifest, HASH)
    dataset.formula_hash = "b" * 64
    db_session.flush()

    with pytest.raises(ValueError, match="lineage differ"):
        create_deployment_evidence(
            db_session,
            candidate_id=candidate.candidate_id,
            gate_decision_id=gate.decision_id,
            approval_id="APPROVE-1",
            code_sha=candidate.code_sha,
        )


def test_deployment_rejects_stale_prerequisite_gate_lineage(db_session):
    candidate, gate, _params = _seed_candidate_and_gate(db_session)
    eval_run = db_session.get(models.AlgorithmEvalRun, "eval-1")
    eval_run.data_manifest_hash = "b" * 64
    db_session.flush()

    with pytest.raises(ValueError, match="lineage differs"):
        create_deployment_evidence(
            db_session,
            candidate_id=candidate.candidate_id,
            gate_decision_id=gate.decision_id,
            approval_id="APPROVE-1",
            code_sha=candidate.code_sha,
        )


def test_deployment_requires_due_cohort_and_crawler_health(db_session):
    candidate, gate, _params = _seed_candidate_and_gate(db_session)
    eval_run = db_session.get(models.AlgorithmEvalRun, "eval-1")
    eval_run.metrics = {**eval_run.metrics, "g_a_due_cohort_healthy": False}
    db_session.flush()

    with pytest.raises(ValueError, match="G-A"):
        create_deployment_evidence(
            db_session,
            candidate_id=candidate.candidate_id,
            gate_decision_id=gate.decision_id,
            approval_id="APPROVE-1",
            code_sha=candidate.code_sha,
        )


def test_deployment_rejects_one_notice_g_c_after_large_g_b(db_session):
    candidate, gate, _params = _seed_candidate_and_gate(db_session)
    eval_run = db_session.get(models.AlgorithmEvalRun, "eval-1")
    eval_run.metrics = {
        **eval_run.metrics,
        "g_c_paired_distinct_notice_count": 1,
    }
    db_session.flush()

    with pytest.raises(ValueError, match="G-C"):
        create_deployment_evidence(
            db_session,
            candidate_id=candidate.candidate_id,
            gate_decision_id=gate.decision_id,
            approval_id="APPROVE-1",
            code_sha=candidate.code_sha,
        )


def test_deployment_rejects_nonfinite_g_c_metric(db_session):
    candidate, gate, _params = _seed_candidate_and_gate(db_session)
    eval_run = db_session.get(models.AlgorithmEvalRun, "eval-1")
    eval_run.metrics = {
        **eval_run.metrics,
        "g_c_primary_effect_ci_lower": float("nan"),
    }
    db_session.flush()

    with pytest.raises(ValueError, match="finite"):
        create_deployment_evidence(
            db_session,
            candidate_id=candidate.candidate_id,
            gate_decision_id=gate.decision_id,
            approval_id="APPROVE-1",
            code_sha=candidate.code_sha,
        )


def test_competitor_output_after_deadline_is_ineligible():
    with pytest.raises(ValidationError, match="before deadline"):
        CompetitorObservationContract(
            observation_id="obs-1",
            provider="DIMA",
            notice_id="N-1",
            as_of_cutoff=NOW,
            observed_at=NOW + timedelta(hours=2),
            deadline_at=NOW + timedelta(hours=1),
            recommendation_price=10_000,
            artifact_hash=HASH,
            artifact_uri="artifact://sha256/abc",
            terms_scope="approved account export",
        )


def test_decision_endpoint_treats_unique_race_as_idempotent_duplicate(pro_client, db_session, monkeypatch):
    """같은 idempotency_key 가 동시에 두 번 오면 진 쪽은 IntegrityError 를 받는다.

    회귀(#128 리뷰): 엔드포인트가 LookupError/PermissionError/ValueError 만 잡아
    유니크 경합이 500 으로 새고 세션이 롤백되지 않은 채 남았다. 레포 관례(growth.py)
    대로 IntegrityError 를 잡아 기존 행을 idempotent duplicate 로 돌려준다.
    """
    from sqlalchemy.exc import IntegrityError
    from app.api.v1.endpoints import recommendation_events as ep

    user = db_session.query(models.User).filter(models.User.email == "test-pro@test.com").first()
    recommendation = record_recommendation(db_session, _recommendation(), user_id=user.id)
    db_session.commit()
    body = {"idempotency_key": "race-key-0001", "event_type": "EXPOSED"}

    # 1) 정상 첫 기록
    first = pro_client.post(f"/api/v1/recommendations/{recommendation.recommendation_id}/decisions", json=body)
    assert first.status_code == 201, first.text

    # 2) 경합의 진 쪽 재현: 조회 시점엔 없었는데(.first() None) commit 에서 유니크 충돌
    real = ep.record_user_decision
    calls = {"n": 0}

    def _racing(db, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            # 조회는 통과한 것처럼 새 행을 flush 하고 commit 단계에서 IntegrityError 를 흉내
            raise IntegrityError("INSERT user_decision_events", {}, Exception("UNIQUE constraint failed"))
        return real(db, **kw)

    monkeypatch.setattr(ep, "record_user_decision", _racing)
    second = pro_client.post(f"/api/v1/recommendations/{recommendation.recommendation_id}/decisions", json=body)
    assert second.status_code in (200, 201), second.text
    assert second.json()["duplicate"] is True
    assert second.json()["id"] == first.json()["id"]


def test_decision_endpoint_race_on_foreign_recommendation_is_403_not_duplicate(pro_client, db_session, monkeypatch):
    """경합 경로도 서비스 계약을 따른다: 같은 키를 다른 recommendation 에 쓰면 duplicate 가 아니라 403."""
    from sqlalchemy.exc import IntegrityError
    from app.api.v1.endpoints import recommendation_events as ep

    user = db_session.query(models.User).filter(models.User.email == "test-pro@test.com").first()
    rec_a = record_recommendation(db_session, _recommendation(), user_id=user.id)
    rec_b = record_recommendation(db_session, _recommendation().model_copy(update={"recommendation_id": "rec-foreign-0002"}), user_id=user.id)
    db_session.commit()
    body = {"idempotency_key": "race-key-foreign-01", "event_type": "EXPOSED"}
    assert pro_client.post(f"/api/v1/recommendations/{rec_a.recommendation_id}/decisions", json=body).status_code == 201

    real = ep.record_user_decision; calls = {"n": 0}
    def _racing(db, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise IntegrityError("INSERT user_decision_events", {}, Exception("UNIQUE constraint failed"))
        return real(db, **kw)
    monkeypatch.setattr(ep, "record_user_decision", _racing)
    foreign = pro_client.post(f"/api/v1/recommendations/{rec_b.recommendation_id}/decisions", json=body)
    assert foreign.status_code == 403, foreign.text
