"""
자가보정 폐쇄 루프 오케스트레이터
==================================
새 개찰 결과가 쌓일 때마다 입찰가 산정 파라미터를 자동 재최적화한다.
출력(채택된 파라미터)이 다음 사이클의 baseline 이 되는 폐쇄 루프.

흐름: 데이터 적재 → 위험모델 적합 → 위험제약 최적화 → 가드 검증 → 채택/롤백
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app.services.autocalibrate import dataset as ds
from app.services.autocalibrate import guard as guard_mod
from app.services.autocalibrate import optimizer
from app.services.autocalibrate.risk_model import ReservedRatioModel
from app.services.autocalibrate.strategy_store import (
    StrategyVersion,
    get_default_store,
    make_version_id,
)


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

    def summary(self) -> str:
        if self.skipped:
            return f"[SKIP] {self.reason}"
        status = "DRY-RUN" if self.dry_run else ("ADOPTED" if self.adopted else "REJECTED")
        return (
            f"[{status}] {self.baseline_version} → {self.candidate_version} | "
            f"위험모델 캘리브레이션 오차 {self.risk_calibration_error*100:.3f}%p"
        )


def should_recalibrate(records: list) -> bool:
    """데이터 fingerprint 가 직전 학습 시점과 다르면 재최적화 필요."""
    store = get_default_store()
    try:
        active = store.load_active()
        return ds.data_fingerprint(records) != active.data_fingerprint
    except FileNotFoundError:
        return True


def run_calibration_cycle(
    trigger: str = "manual",
    dry_run: bool = False,
    **objective_kwargs,
) -> CycleReport:
    """자가보정 사이클 1회 실행.

    Args:
        trigger: "manual" | "scheduled" | "new_data"
        dry_run: True 면 후보 생성·검증만 하고 저장소를 변경하지 않음
        objective_kwargs: lam, gamma, tau, eta — 목적함수 하이퍼파라미터 오버라이드
    """
    store = get_default_store()
    # 부트스트랩 보장 (calculator.BID_STRATEGY → v0)
    from app.services.calculator import BID_STRATEGY

    store.ensure_bootstrap(BID_STRATEGY)

    # ── 1. 데이터 적재 ──────────────────────────────────────
    records = ds.load_records()
    if not records:
        return CycleReport(skipped=True, reason="데이터 없음")

    baseline = store.load_active()
    fingerprint = ds.data_fingerprint(records)

    if trigger != "manual" and fingerprint == baseline.data_fingerprint:
        return CycleReport(
            skipped=True,
            reason="새 데이터 없음 (fingerprint 동일)",
            baseline_version=baseline.version_id,
        )

    # ── 2. 위험모델 적합 ────────────────────────────────────
    year_weights = optimizer.adaptive_year_weights(records)
    risk_model = ReservedRatioModel.fit(records, year_weights)

    # ── 3. 위험제약 최적화 ──────────────────────────────────
    new_params = optimizer.optimize_all(
        records, risk_model, baseline.params, year_weights, **objective_kwargs
    )

    # ── 4. 가드 검증 ────────────────────────────────────────
    decision = guard_mod.evaluate_candidate(new_params, baseline.params, records)
    cal_error = risk_model.calibration_error(records, new_params)

    candidate = StrategyVersion(
        version_id=make_version_id(),
        created_at=datetime.now().isoformat(timespec="seconds"),
        params=new_params,
        parent_version=baseline.version_id,
        data_fingerprint=fingerprint,
        year_weights={str(k): v for k, v in year_weights.items()},
        metrics={
            **decision.insample_metrics,
            "risk_calibration_error": round(cal_error, 5),
        },
        notes=" | ".join(decision.reasons),
    )

    # ── 5. 채택 또는 롤백 ───────────────────────────────────
    adopted = False
    if decision.accepted and not dry_run:
        store.commit(candidate)
        # calculator 캐시 무효화 (long-running API 프로세스 대비)
        from app.services.calculator import reload_strategy_cache

        reload_strategy_cache()
        adopted = True
    elif not decision.accepted and not dry_run:
        store.save_rejected(candidate)

    return CycleReport(
        skipped=False,
        adopted=adopted,
        dry_run=dry_run,
        candidate_version=candidate.version_id,
        baseline_version=baseline.version_id,
        decision=decision,
        risk_calibration_error=cal_error,
        year_weights={str(k): v for k, v in year_weights.items()},
    )
