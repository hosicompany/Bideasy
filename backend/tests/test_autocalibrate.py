"""
자가보정 알고리즘 회귀 테스트
==============================
- strategy_store: 부트스트랩 멱등성, commit/archive, rollback, save_rejected
- guard: 일부러 나쁜 후보를 거부하는지
- risk_model: 캘리브레이션 오차가 합리적 범위인지
- 부트스트랩 동등성: 동적 로딩 전환이 무손실인지
"""

from dataclasses import replace

import pytest

from app.services.autocalibrate.strategy_store import (
    BOOTSTRAP_VERSION_ID,
    FileStrategyStore,
    StrategyVersion,
    make_version_id,
)
from app.services.autocalibrate import dataset as ds
from app.services.autocalibrate import guard
from app.services.autocalibrate import optimizer
from app.services.autocalibrate.ratio_error import TIE_MARGIN, walk_forward_validate
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


def test_ratio_error_walk_forward_uses_past_only_and_selects_shadow_candidate(records):
    report = walk_forward_validate(records, BID_STRATEGY)

    assert report["selected_shadow_candidate"] == "segment_median"
    assert report["promotion_allowed"] is False
    assert report["pooled"]["segment_median"]["mae"] < report["pooled"][
        "active_adjustment"
    ]["mae"]
    for fold in report["folds"]:
        assert all(year < fold["holdout_year"] for year in fold["train_years"])
        assert fold["segment_median"]["delta_vs_active"] < 0


def test_ratio_error_future_outcome_cannot_change_earlier_fold(records):
    before = walk_forward_validate(records, BID_STRATEGY)
    mutated = list(records)
    future_index = next(i for i, record in enumerate(mutated) if record.year == 2025)
    future = mutated[future_index]
    mutated[future_index] = replace(
        future,
        reserved_price=future.basic_price * 1.05,
    )

    after = walk_forward_validate(mutated, BID_STRATEGY)
    before_2024 = next(
        fold for fold in before["folds"] if fold["holdout_year"] == 2024
    )
    after_2024 = next(
        fold for fold in after["folds"] if fold["holdout_year"] == 2024
    )

    assert after_2024 == before_2024


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


def test_db_records_use_lower_limits_single_source(db_session):
    """DB 병합분의 하한율은 `lower_limits` 에서 온다 — 상수 하드코딩 금지.

    예전에는 87.745 를 박아 두었다. 2026-01-30 요율 개정(10억 미만 공사
    89.745%) 이후로는 그 값이 실제 하한선과 달라, 판정이 통째로 어긋난다.
    """
    from datetime import datetime
    from app.db import models
    from app.services.autocalibrate.dataset import load_records
    from app.services.lower_limits import get_lower_limit_rate

    db_session.add(models.OpeningResult(
        bid_no="LLRTEST-1", organization="A기관", bid_method="적격심사제",
        open_date=datetime(2026, 6, 1),          # 개정 이후
        basic_price=5e8,                          # 3억~10억 → 89.745%
        reserved_price=5.02e8, winner_price=4.5e8, winner_rate=90.0,
    ))
    db_session.flush()   # 커밋하면 뒤 테스트로 샌다 (픽스처는 rollback 만 한다)

    rec = next(r for r in load_records(db=db_session) if r.bid_no == "LLRTEST-1")
    expected = get_lower_limit_rate("CONSTRUCTION", 5e8, datetime(2026, 6, 1).date())
    assert rec.lower_limit_rate == expected
    assert rec.lower_limit_rate != 87.745, "구 상수로 회귀했다"


def test_db_records_pre_revision_keeps_old_rate(db_session):
    """개정 전 공고는 구 요율을 그대로 써야 한다 — 날짜를 무시하면 과거가 왜곡된다."""
    from datetime import datetime
    from app.db import models
    from app.services.autocalibrate.dataset import load_records

    db_session.add(models.OpeningResult(
        bid_no="LLRTEST-2", organization="B기관", bid_method="적격심사제",
        open_date=datetime(2025, 6, 1),          # 개정 이전
        basic_price=5e8,
        reserved_price=5.02e8, winner_price=4.5e8, winner_rate=90.0,
    ))
    db_session.flush()   # 커밋하면 뒤 테스트로 샌다 (픽스처는 rollback 만 한다)

    rec = next(r for r in load_records(db=db_session) if r.bid_no == "LLRTEST-2")
    assert rec.lower_limit_rate == 87.745


def test_ratio_error_reports_that_baseline_is_not_walk_forward(records):
    """기준선이 fold 별 재적합이 아니라는 사실이 결과에 박혀 있어야 한다.

    기준선은 2021~2025 로 적합된 저장본이라 2022~2025 holdout 에서 미래를
    본다. 방향은 안전하지만(기준선에 유리) delta 를 성과로 인용하면 과대평가가
    아니라 과소평가된 수치를 근거로 쓰게 된다. JSON 만 보고 판단하는 다음
    세션이 속지 않도록 페이로드가 스스로 밝히게 한다.
    """
    report = walk_forward_validate(records, BID_STRATEGY)

    assert report["baseline_is_walk_forward"] is False
    assert any("walk-forward 가 아니다" in note for note in report["notes"])


def test_ratio_error_prefers_simpler_candidate_when_indistinguishable(records):
    """두 후보가 구분되지 않으면 덜 쪼갠 쪽이 이긴다.

    실측 pooled MAE 는 세그먼트 중앙값과 기관 부분풀링이 0.00001 수준으로
    갈린다 — 연도 하나만 바뀌어도 순위가 뒤집히는 차이다. 순수 MAE 최소로
    고르면 그 노이즈가 기관 차원을 채택시킨다.

    차이가 TIE_MARGIN 을 넘어서면 이 단언이 깨지는데, 그건 테스트의 실패가
    아니라 **기관 차원이 실제로 신호를 갖게 됐다는 신호**다. 그때는 다시 재라.
    """
    report = walk_forward_validate(records, BID_STRATEGY)
    simple = report["pooled"]["segment_median"]["mae"]
    complex_ = report["pooled"]["organization_shrunk"]["mae"]

    assert abs(complex_ - simple) <= TIE_MARGIN, (
        f"기관 차원이 구분 가능해졌다 (차이 {abs(complex_ - simple):.6f} "
        f"> TIE_MARGIN {TIE_MARGIN}) — 후보 선택을 재검토할 것"
    )
    assert report["selected_shadow_candidate"] == "segment_median"


# ── R1: 파라미터화 ratio_pinned_v2 계약 ──────────────────────────────
# 옛 2축 탐색은 J 가 (adj, margin) 을 곱으로만 보는 탓에 adjustment 를 식별하지
# 못했다(§9 2026-08-13). 아래 넷은 그 수습이 되돌아가지 않게 잡아 둔다.

def test_optimizer_pins_adjustment_instead_of_searching_it(records):
    """adjustment 는 탐색 대상이 아니다 — 사정률 중심에 고정된다."""
    weights = optimizer.adaptive_year_weights(records)
    risk_model = ReservedRatioModel.fit(records, weights)

    checked = 0
    for method, bracket in (("적격심사제", "medium"), ("소액수의견적", "small")):
        cand = optimizer.optimize_segment(records, method, bracket, risk_model)
        if cand is None:
            continue
        checked += 1
        assert cand.adjustment == optimizer.pinned_adjustment(
            risk_model, method, bracket
        ), f"{method}/{bracket} 의 adjustment 가 고정값과 다르다 — 축이 되살아났다"
    assert checked, "검증한 세그먼트가 없다"


def test_margin_grid_does_not_shrink_product_reach():
    """축을 줄이되 곱의 도달 범위는 줄이지 않는다.

    상한을 상수로 박으면 고정된 adjustment 에 따라 공격적인 쪽 후보가 조용히
    잘린다. 그러면 성능 변화가 축 변경 탓인지 격자가 좁아진 탓인지 못 가른다.
    """
    lower = 89.745
    old_reach = (1 + max(optimizer._ADJ_RANGE) / 100) * (
        lower + max(optimizer._MARGIN_RANGE)
    )
    for adj in (-1.0, -0.5, -0.1, 0.0, 0.5, 1.0):
        grid = optimizer.margin_grid(lower, adj)
        assert grid[0] == 0.0, "하한율 미만은 정의상 무효라 0.0 에서 시작해야 한다"
        reach = (1 + adj / 100) * (lower + max(grid))
        assert reach >= old_reach - 1e-9, f"adj {adj} 에서 곱 상한이 잘렸다"


def test_parametrization_conversion_never_lowers_product():
    """전환의 반올림 잔차는 **항상 안전한 쪽**으로만 남는다.

    곱이 줄면 투찰가가 낙찰하한선에 가까워져 무효 위험이 커진다 — 전환이라는
    이벤트 자체가 사용자를 위험 쪽으로 미는 일은 없어야 한다.
    """
    lower = 89.745
    for old_adj in (-1.0, -0.3, 0.0, 0.5, 0.9):
        for old_margin in (0.1, 0.5, 1.0, 1.4):
            for new_adj in (-0.6, -0.1, 0.0, 1.3):
                new_margin = optimizer.converted_margin(
                    lower, old_adj, old_margin, new_adj
                )
                assert new_margin >= 0.0, "margin 이 음수면 무조건 무효다"
                old_p = (1 + old_adj / 100) * (lower + old_margin)
                new_p = (1 + new_adj / 100) * (lower + new_margin)
                assert new_p >= old_p - 1e-9, (
                    f"곱이 줄었다: adj {old_adj}→{new_adj}, "
                    f"margin {old_margin}→{new_margin} ({old_p:.4f}→{new_p:.4f})"
                )


def test_strategy_version_carries_parametrization():
    """저장된 두 숫자가 어느 축인지 버전이 스스로 밝힌다.

    기본값이 구 축인 이유: 이 필드 이전에 저장된 파일에는 값이 없는데, 그것들은
    전부 2축 자유 탐색 결과다. 새 축으로 읽으면 adjustment 를 사정률 예측으로
    오해한다.
    """
    from app.services.autocalibrate.strategy_store import StrategyVersion

    assert StrategyVersion(version_id="x", created_at="t", params={}).parametrization == (
        "product_v1"
    )
    assert optimizer.PARAMETRIZATION == "ratio_pinned_v2"
    # 옛 JSON(필드 없음)을 읽어도 구 축으로 남아야 한다
    legacy = StrategyVersion.from_dict(
        {"version_id": "old", "created_at": "t", "params": {}}
    )
    assert legacy.parametrization == "product_v1"


def test_thin_method_does_not_dominate_ratio_prediction(records):
    """표본이 얕은 입찰방법의 중앙값이 사정률 예측을 지배하면 안 된다.

    `_by_method` 에는 최소 표본 조건이 없어서 n=1~3 짜리 방법도 부모가 되고,
    희소 세그먼트는 그 분위수를 **통째로** 물려받는다. 실측에서
    `실시설계기술제안입찰`(방법 전체 n=2)의 중앙값 1.0133 이 그대로 예측이 돼
    adjustment 가 +1.3 으로 튀었다 — 표본이 충분한 방법은 전부 −0.1 로
    수렴하므로 신호가 아니라 노이즈다.

    불변식: **얕을수록 전역에 가까워야 한다.** 자기 중앙값보다 전역에서 더
    멀어지는 일은 없어야 한다.
    """
    weights = optimizer.adaptive_year_weights(records)
    rm = ReservedRatioModel.fit(records, weights)
    global_median = rm._global.quantiles.get(0.5)
    assert global_median, "전역 분위수가 없으면 이 검사가 무의미하다"

    checked = 0
    for method, params in rm._by_method.items():
        if params.n_raw >= 30:
            continue
        own_median = params.quantiles.get(0.5)
        if not own_median:
            continue
        checked += 1
        for bracket in ("small", "medium", "large"):
            pred = rm.predict_reserved_ratio(method, bracket)
            assert abs(pred - global_median) <= abs(own_median - global_median) + 1e-9, (
                f"{method}/{bracket}(방법 n={params.n_raw}) 의 예측이 자기 중앙값보다 "
                f"전역에서 멀다 — shrinkage 가 풀렸다"
            )
    assert checked, "얕은 방법이 하나도 없어 검증하지 못했다"


def test_pinned_adjustment_stays_near_ratio_center(records):
    """고정되는 adjustment 는 사정률의 현실 범위 안에 있어야 한다.

    사정률은 예정가격÷기초금액이라 1.0 근처다(실측 전 세그먼트 0.995~1.003).
    ±1%p 를 넘는 adjustment 가 나오면 데이터가 아니라 표본 부족이 만든 값이다
    — 그대로 두면 A값 가격식을 타고 실사용자 투찰가로 나간다.
    """
    weights = optimizer.adaptive_year_weights(records)
    rm = ReservedRatioModel.fit(records, weights)

    for (method, bracket) in rm._segments:
        adj = optimizer.pinned_adjustment(rm, method, bracket)
        assert -1.0 <= adj <= 1.0, (
            f"{method}/{bracket} 의 고정 adjustment {adj:+.1f} 가 사정률 현실 "
            f"범위(±1.0%p) 를 벗어났다"
        )


# ── 기초금액 일관성 필터 (2026-08-17) ────────────────────────────
# `basic_price` 에 추정가격이 든 행이 섞여 있고(함정 22), 자가보정이 그걸
# 사정률로 읽으면 adjustment 가 +6~+10 까지 튄다. 2026-08-16 재보정이 실제로
# 이 이유로 거부됐다.

def test_tainted_basis_rows_are_excluded(db_session):
    """사정률이 1.1 배로 뭉치는 행(추정가격 스냅샷)은 표본에서 빠진다."""
    from datetime import datetime
    from app.db import models
    from app.services.autocalibrate.dataset import load_records

    db_session.add(models.OpeningResult(
        bid_no="TAINT-1", organization="오염기관", bid_method="수의시담",
        open_date=datetime(2026, 6, 2), basic_price=1e8,
        reserved_price=1.10e8,          # ← 1.10 배 = 함정 22 지문
        winner_price=0.95e8, winner_rate=95.0,
    ))
    db_session.add(models.OpeningResult(
        bid_no="CLEAN-1", organization="정상기관", bid_method="수의시담",
        open_date=datetime(2026, 6, 2), basic_price=1e8,
        reserved_price=0.999e8,         # ← 밴드 안
        winner_price=0.95e8, winner_rate=95.0,
    ))
    db_session.commit()

    merged = load_records(db=db_session)
    ids = {r.bid_no for r in merged}
    assert "CLEAN-1" in ids
    assert "TAINT-1" not in ids, "오염 행이 자가보정 표본에 들어왔다"


def test_filter_does_not_touch_static_ledger():
    """정적 원장은 이 필터로 한 건도 줄지 않는다.

    실측(2026-08-17): 4,848건 중 밴드 밖 **0건**. 오염은 운영 DB 병합분에만
    있다. 이 단언이 깨지면 정적 원장 자체가 오염됐다는 뜻이라 필터가 아니라
    원장을 봐야 한다.
    """
    from app.services.autocalibrate.dataset import load_records
    from app.services.bid_data_quality import base_is_consistent

    recs = load_records(db=None)
    assert recs, "정적 원장이 비었다"
    assert all(base_is_consistent(r.basic_price, r.reserved_price) for r in recs)


def test_strategy_version_records_dataset_policy():
    """어떤 코호트 위에서 적합했는지 버전이 밝힌다.

    기본값이 `unfiltered` 인 이유: 이 필드 이전에 저장된 버전들은 오염을
    포함한 표본으로 적합됐다. 새 값으로 읽으면 세대 간 metrics 를 한 선으로
    이어 붙이게 된다.
    """
    from app.services.autocalibrate import dataset as ds
    from app.services.autocalibrate.strategy_store import StrategyVersion

    assert ds.DATASET_POLICY == "base_consistent_v1"
    assert StrategyVersion(
        version_id="x", created_at="t", params={}
    ).dataset_policy == "unfiltered"
    legacy = StrategyVersion.from_dict(
        {"version_id": "old", "created_at": "t", "params": {}}
    )
    assert legacy.dataset_policy == "unfiltered"


def test_weekly_loop_uses_strict_db(monkeypatch):
    """주간 루프는 DB 조회 실패를 삼키지 않는다.

    삼키면 정적 원장만 남은 채로 돌아가는데, 그러면 fingerprint 가 달라져
    **DB 장애를 "새 코호트"로 오인하고 재보정**한다 — 표본이 반쯤 사라진
    상태의 재적합이다.
    """
    from app.services.autocalibrate import loop as loop_mod

    # ⚠️ 소스 문자열 검사(`"strict_db=True" in getsource`)로는 안 된다 —
    # 주석에 그 문자열이 있으면 인자를 지워도 통과한다(실제로 겪음).
    # 호출 인자를 직접 잡는다.
    captured: dict = {}

    def _fake_load(*args, **kwargs):
        captured.update(kwargs)
        return []          # 빈 표본 → 사이클은 곧바로 skip 반환

    monkeypatch.setattr(loop_mod.ds, "load_records", _fake_load)
    loop_mod.run_calibration_cycle(trigger="scheduled", db=object())

    assert captured.get("strict_db") is True, "주간 루프가 DB 장애를 삼킨다"
