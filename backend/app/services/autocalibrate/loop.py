"""
자가보정 폐쇄 루프 오케스트레이터
==================================
새 개찰 결과가 쌓일 때마다 입찰가 산정 파라미터 후보를 재최적화한다.
이 루프는 후보 생성·평가까지만 수행하며 active 전략을 바꾸지 않는다.
승격은 저장된 후보를 검증된 증거 그래프와 연결하는 별도 승인 경로의 책임이다.

흐름: 데이터 적재 → 시간 분리 → 위험모델 적합 → 최적화 → 가드 → 후보/승격
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.services.autocalibrate import dataset as ds
from app.services.autocalibrate import guard as guard_mod
from app.services.autocalibrate import optimizer
from app.services.autocalibrate.risk_model import ReservedRatioModel
from app.services.autocalibrate.strategy_store import (
    PromotionAuthorizationError,
    StrategyVersion,
    get_default_store,
    make_version_id,
)


DEFAULT_VALIDATION_YEARS = (2025,)
DEFAULT_SEALED_HOLDOUT_YEARS = (2026,)
MIN_TRAIN_SAMPLES = 100
MIN_VALIDATION_SAMPLES = 100
# 기존 G-B와 같은 distinct clean notice 하한. 이 루프는 행을 증식하지 않으므로
# BidRecord 한 건이 공고 한 건이다.


@dataclass
class CycleReport:
    """자가보정 사이클 1회 실행 결과."""

    skipped: bool = False
    reason: str = ""
    adopted: bool = False
    dry_run: bool = False
    candidate_version: str = ""
    baseline_version: str = ""
    decision: guard_mod.GuardDecision | None = None
    risk_calibration_error: float = 0.0
    year_weights: dict = field(default_factory=dict)
    data_quality: dict = field(default_factory=dict)
    temporal_counts: dict = field(default_factory=dict)
    gate_decision: str = "NOT_EVALUATED"
    approval_id: str | None = None
    candidate_saved: bool = False

    def summary(self) -> str:
        if self.skipped:
            return f"[SKIP] {self.reason}"
        if self.dry_run:
            status = "DRY-RUN"
        elif self.adopted:
            status = "ADOPTED"
        elif self.candidate_saved:
            status = "CANDIDATE"
        else:
            status = "REJECTED"
        return (
            f"[{status}] {self.baseline_version} → {self.candidate_version} | "
            f"위험모델 캘리브레이션 오차 {self.risk_calibration_error*100:.3f}%p"
        )


def should_recalibrate(records: list) -> bool:
    """데이터 fingerprint가 직전 평가 시점과 다르면 재최적화 필요."""
    store = get_default_store()
    try:
        fingerprint = ds.data_fingerprint(records)
        evaluated = [
            version
            for version in store.list_versions()
            if version.data_fingerprint
            and version.status in {"active", "candidate", "rejected"}
        ]
        if evaluated:
            latest = max(evaluated, key=lambda version: (version.created_at, version.version_id))
            return fingerprint != latest.data_fingerprint
        return fingerprint != store.load_active().data_fingerprint
    except FileNotFoundError:
        return True


def run_calibration_cycle(
    trigger: str = "manual",
    dry_run: bool = False,
    db=None,
    *,
    gate_decision: str | None = None,
    approval_id: str | None = None,
    validation_years: tuple[int, ...] = DEFAULT_VALIDATION_YEARS,
    sealed_holdout_years: tuple[int, ...] = DEFAULT_SEALED_HOLDOUT_YEARS,
    min_train_samples: int = MIN_TRAIN_SAMPLES,
    min_validation_samples: int = MIN_VALIDATION_SAMPLES,
    **objective_kwargs,
) -> CycleReport:
    """자가보정 사이클 1회 실행.

    Args:
        trigger: "manual" | "scheduled" | "new_data"
        dry_run: True 면 후보 생성·검증만 하고 저장소를 변경하지 않음
        db: 제공 시 누적 opening_results 도 학습 데이터에 병합 (최신 시장 반영)
        gate_decision: 폐기된 인라인 승격 인자. 전달하면 fail-closed
        approval_id: 폐기된 인라인 승격 인자. 전달하면 fail-closed
        objective_kwargs: lam, gamma, tau, eta — 목적함수 하이퍼파라미터 오버라이드
    """
    if gate_decision is not None or approval_id is not None:
        raise PromotionAuthorizationError(
            "자가보정 루프의 인라인 승격은 비활성화되었습니다. "
            "후보를 먼저 기록한 뒤 검증된 GateDecision과 별도 운영 승인을 "
            "사용하는 승격 경로를 이용하세요."
        )

    store = get_default_store()
    # 부트스트랩 보장 (calculator.BID_STRATEGY → v0)
    from app.services.calculator import BID_STRATEGY

    store.ensure_bootstrap(BID_STRATEGY)

    # ── 1. 데이터 적재 (정적 + 누적 DB) ─────────────────────
    # 후보가 무엇인지 결정하기 전에 정보 경계를 한 번만 동결한다. 이후 수집된
    # 결과는 이번 validation에도 들어갈 수 없고, sealed outcome은 별도 EvalRun이
    # 나중에 수집한다.
    cycle_frozen_at = datetime.now(timezone.utc)
    quality_stats = ds.DatasetQualityStats()
    records = ds.load_records(
        # 주간 후보 생성기는 sealed 연도 outcome 자체를 읽지 않는다. DB 적재도
        # 같은 반개구간을 적용하므로 sealed 값이 메모리/fingerprint에 나타나지 않는다.
        year_range=(2021, min(sealed_holdout_years)),
        db=db,
        strict_db=db is not None,
        quality_stats=quality_stats,
        enforce_base_consistency=True,
        require_a_value_status=True,
        require_observation_time=True,
        require_feature_lineage=True,
    )
    if not records:
        return CycleReport(
            skipped=True,
            reason="유효 데이터 없음",
            data_quality=quality_stats.as_dict(),
        )

    temporal = ds.split_temporal_records(
        records,
        validation_years=validation_years,
        sealed_holdout_years=sealed_holdout_years,
        candidate_selected_at=cycle_frozen_at,
        require_known_observation=True,
    )
    # 후보의 lineage/fingerprint에는 후보 생성에 실제로 사용 가능한 train과
    # validation만 포함한다. sealed outcome의 값이나 정정 내용은 optimizer,
    # guard, candidate metadata 어느 곳에도 전달하지 않는다.
    candidate_evidence = [*temporal.train, *temporal.validation]
    baseline = store.load_active()
    fingerprint = ds.data_fingerprint(candidate_evidence)

    if trigger != "manual" and not should_recalibrate(candidate_evidence):
        return CycleReport(
            skipped=True,
            reason="새 데이터 없음 (fingerprint 동일)",
            baseline_version=baseline.version_id,
            data_quality=quality_stats.as_dict(),
        )

    if len(temporal.train) < min_train_samples:
        return CycleReport(
            skipped=True,
            reason=f"train 표본 부족: {len(temporal.train)} < {min_train_samples}",
            baseline_version=baseline.version_id,
            data_quality=quality_stats.as_dict(),
            temporal_counts=temporal.counts,
        )

    # ── 2. 위험모델 적합 ────────────────────────────────────
    # sealed holdout과 validation은 fit/후보 선택에 절대 전달하지 않는다.
    year_weights = optimizer.adaptive_year_weights(temporal.train)
    risk_model = ReservedRatioModel.fit(temporal.train, year_weights)

    # ── 3. 위험제약 최적화 ──────────────────────────────────
    new_params = optimizer.optimize_all(
        temporal.train,
        risk_model,
        baseline.params,
        year_weights,
        **objective_kwargs,
    )

    # ── 4. 가드 검증 ────────────────────────────────────────
    # 후보 선택은 validation에서 끝낸다. sealed_test는 후보와 manifest를 고정한
    # 뒤 독립 EvalRun이 정확히 한 번 여는 최종 gate이며, 주간 루프가 반복해서
    # 들여다보면 더 이상 sealed가 아니다.
    decision = guard_mod.evaluate_candidate(
        new_params,
        baseline.params,
        temporal.validation,
        holdout_records=[],
        min_validation_samples=min_validation_samples,
    )
    cal_error = risk_model.calibration_error(temporal.validation, new_params)
    candidate = StrategyVersion(
        version_id=make_version_id(),
        created_at=cycle_frozen_at.isoformat(timespec="seconds"),
        params=new_params,
        parent_version=baseline.version_id,
        data_fingerprint=fingerprint,
        year_weights={str(k): v for k, v in year_weights.items()},
        metrics={
            **decision.insample_metrics,
            "risk_calibration_error": round(cal_error, 5),
            "validation": decision.insample_metrics,
            "sealed_holdout": {
                "status": "SEALED_NOT_OPENED",
                "count": len(temporal.sealed_holdout),
            },
            "temporal_counts": temporal.counts,
            "training_cutoff_at": (
                temporal.training_cutoff_at.isoformat()
                if temporal.training_cutoff_at
                else None
            ),
            "candidate_selected_at": (
                temporal.candidate_selected_at.isoformat()
                if temporal.candidate_selected_at
                else None
            ),
            "data_quality": quality_stats.as_dict(),
        },
        notes=" | ".join(decision.reasons),
        gate_decision="NOT_EVALUATED",
    )

    # ── 5. 후보 기록 (active는 이 루프에서 절대 변경하지 않음) ──
    candidate_saved = False
    if decision.accepted and not dry_run:
        store.save_candidate(candidate)
        candidate_saved = True
    elif not decision.accepted and not dry_run:
        store.save_rejected(candidate)

    return CycleReport(
        skipped=False,
        adopted=False,
        dry_run=dry_run,
        candidate_version=candidate.version_id,
        baseline_version=baseline.version_id,
        decision=decision,
        risk_calibration_error=cal_error,
        year_weights={str(k): v for k, v in year_weights.items()},
        data_quality=quality_stats.as_dict(),
        temporal_counts=temporal.counts,
        gate_decision="NOT_EVALUATED",
        approval_id=None,
        candidate_saved=candidate_saved,
    )
