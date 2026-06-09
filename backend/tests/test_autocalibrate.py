"""
자가보정 알고리즘 회귀 테스트
==============================
- strategy_store: 부트스트랩 멱등성, commit/archive, rollback, save_rejected
- guard: 일부러 나쁜 후보를 거부하는지
- risk_model: 캘리브레이션 오차가 합리적 범위인지
- 부트스트랩 동등성: 동적 로딩 전환이 무손실인지
"""

import pytest

from app.services.autocalibrate.strategy_store import (
    BOOTSTRAP_VERSION_ID,
    FileStrategyStore,
    StrategyVersion,
    make_version_id,
)
from app.services.autocalibrate import dataset as ds
from app.services.autocalibrate import guard
from app.services.autocalibrate.risk_model import ReservedRatioModel
from app.services.calculator import BID_STRATEGY


@pytest.fixture
def temp_store(tmp_path):
    """격리된 임시 디렉터리 기반 전략 저장소."""
    return FileStrategyStore(base_dir=tmp_path / "strategy")


@pytest.fixture
def records():
    """실제 과거 데이터 (없으면 해당 테스트 skip)."""
    recs = ds.load_records()
    if not recs:
        pytest.skip("opening_results_*.json 데이터 없음")
    return recs


# ── strategy_store ───────────────────────────────────────────
def test_bootstrap_creates_v0(temp_store):
    temp_store.ensure_bootstrap({"DEFAULT": {"small": (-0.3, 1.0)}})
    active = temp_store.load_active()
    assert active.version_id == BOOTSTRAP_VERSION_ID
    # 튜플 → 리스트 정규화
    assert active.params["DEFAULT"]["small"] == [-0.3, 1.0]


def test_bootstrap_idempotent(temp_store):
    temp_store.ensure_bootstrap({"DEFAULT": {"small": (-0.3, 1.0)}})
    # 두 번째 호출은 무시되어야 함
    temp_store.ensure_bootstrap({"DEFAULT": {"small": (99.0, 99.0)}})
    active = temp_store.load_active()
    assert active.params["DEFAULT"]["small"] == [-0.3, 1.0]


def test_commit_archives_previous(temp_store):
    temp_store.ensure_bootstrap({"DEFAULT": {"small": (-0.3, 1.0)}})
    v = StrategyVersion(
        version_id=make_version_id(),
        created_at="2026-01-01T00:00:00",
        params={"DEFAULT": {"small": (0.5, 0.5)}},
        parent_version=BOOTSTRAP_VERSION_ID,
    )
    temp_store.commit(v)
    assert temp_store.load_active().version_id == v.version_id
    prev = temp_store.get(BOOTSTRAP_VERSION_ID)
    assert prev is not None and prev.status == "archived"


def test_rollback_restores_old_version(temp_store):
    temp_store.ensure_bootstrap({"DEFAULT": {"small": (-0.3, 1.0)}})
    v = StrategyVersion(
        version_id="v_new",
        created_at="2026-01-01T00:00:00",
        params={"DEFAULT": {"small": (0.5, 0.5)}},
    )
    temp_store.commit(v)
    temp_store.rollback(BOOTSTRAP_VERSION_ID)
    active = temp_store.load_active()
    assert active.version_id == BOOTSTRAP_VERSION_ID
    assert active.params["DEFAULT"]["small"] == [-0.3, 1.0]


def test_save_rejected_keeps_active_unchanged(temp_store):
    """거부된 후보는 기록만 되고 active 는 불변 (= 자동 롤백)."""
    temp_store.ensure_bootstrap({"DEFAULT": {"small": (-0.3, 1.0)}})
    bad = StrategyVersion(
        version_id="v_bad",
        created_at="2026-01-01T00:00:00",
        params={"DEFAULT": {"small": (9.0, 9.0)}},
    )
    temp_store.save_rejected(bad)
    assert temp_store.load_active().version_id == BOOTSTRAP_VERSION_ID
    rejected = temp_store.get("v_bad")
    assert rejected is not None and rejected.status == "rejected"


# ── guard ────────────────────────────────────────────────────
def test_guard_rejects_dropout_spiking_candidate(records):
    """모든 margin 을 0 으로 만든 후보 → 탈락률 폭증 → 가드 거부."""
    bad = {
        method: {bracket: [v[0], 0.0] for bracket, v in brackets.items()}
        for method, brackets in BID_STRATEGY.items()
    }
    decision = guard.evaluate_candidate(bad, BID_STRATEGY, records)
    assert not decision.accepted
    assert decision.metric_deltas["dropout_rate"] > 0  # 탈락률 악화


def test_guard_accepts_identical_candidate(records):
    """baseline 과 동일한 후보 → 게이트 통과 (악화 없음)."""
    decision = guard.evaluate_candidate(BID_STRATEGY, BID_STRATEGY, records)
    assert decision.accepted
    assert decision.metric_deltas["dropout_rate"] == 0


# ── risk_model ───────────────────────────────────────────────
def test_risk_model_calibration_reasonable(records):
    """위험모델 예측 탈락률 vs 실측 괴리가 2%p 미만 (모델 신뢰도)."""
    rm = ReservedRatioModel.fit(records)
    err = rm.calibration_error(records, BID_STRATEGY)
    assert err < 0.02, f"캘리브레이션 오차 {err*100:.2f}%p — 위험모델 신뢰도 부족"


def test_critical_ratio_monotonic():
    """임계비율 r* 는 margin 증가 시 단조 증가 (수식 검증)."""
    r1 = ReservedRatioModel.critical_ratio(adjustment=0.0, margin=0.5, lower_rate=87.745)
    r2 = ReservedRatioModel.critical_ratio(adjustment=0.0, margin=1.5, lower_rate=87.745)
    assert r2 > r1  # margin 클수록 더 높은 r 까지 통과 가능


# ── 데이터셋 ─────────────────────────────────────────────────
def test_data_fingerprint_stable(records):
    """같은 데이터는 같은 fingerprint."""
    fp1 = ds.data_fingerprint(records)
    fp2 = ds.data_fingerprint(records)
    assert fp1 == fp2
    # 한 건 빼면 다른 fingerprint
    fp3 = ds.data_fingerprint(records[:-1])
    assert fp3 != fp1


def test_bracket_boundaries():
    """금액대 경계값 검증."""
    assert ds.get_bracket(9_999_9999) == "small"
    assert ds.get_bracket(1e8) == "medium"
    assert ds.get_bracket(5e8) == "large"
    assert ds.get_bracket(1e9) == "xlarge"
    assert ds.get_bracket(5e9) == "xxlarge"


def test_load_records_merges_db(db_session):
    """누적 opening_results 가 load_records(db=) 에 병합되는지."""
    from datetime import datetime
    from app.db import models
    from app.services.autocalibrate.dataset import load_records

    db_session.add(models.OpeningResult(
        bid_no="OPRTEST-1", organization="A기관", bid_method="적격심사제",
        open_date=datetime(2026, 6, 1), basic_price=1e8, reserved_price=1.005e8,
        winner_price=0.88e8, winner_rate=88.0, participants_count=5,
    ))
    db_session.commit()

    static_only = load_records()
    merged = load_records(db=db_session)
    assert len(merged) == len(static_only) + 1
    assert any(r.bid_no == "OPRTEST-1" for r in merged)
    # 무효 데이터(가격 0)는 제외
    assert all(r.basic_price > 0 and r.winner_price > 0 for r in merged)
