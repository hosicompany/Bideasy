"""
자가보정 알고리즘 회귀 테스트
==============================
- strategy_store: 부트스트랩 멱등성, commit/archive, rollback, save_rejected
- guard: 일부러 나쁜 후보를 거부하는지
- risk_model: 캘리브레이션 오차가 합리적 범위인지
- 부트스트랩 동등성: 동적 로딩 전환이 무손실인지
"""

import json
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.services.autocalibrate.strategy_store import (
    BOOTSTRAP_VERSION_ID,
    FileStrategyStore,
    PromotionAuthorizationError,
    StrategyVersion,
)
from app.services.autocalibrate import dataset as ds
from app.services.autocalibrate import guard
from app.services.autocalibrate.optimizer import evaluate_params
from app.services.autocalibrate.risk_model import ReservedRatioModel
from app.services.calculator import BID_STRATEGY


def test_rate_error_uses_common_confirmed_basis_denominator():
    record = ds.BidRecord(
        bid_no="RATE-BASIS-1",
        title="",
        org="",
        bid_method="적격심사제",
        basic_price=100_000_000,
        estimated_price=0,
        reserved_price=102_000_000,
        winner_price=90_000_000,
        winner_rate=88.2353,  # winner/reserved; deliberately different denominator
        lower_limit_rate=87.745,
        year=2025,
        a_value=0,
        a_value_status="not_applicable",
    )
    params = {"적격심사제": {"medium": [0.0, 2.255]}, "DEFAULT": {}}

    metrics = evaluate_params([record], params)

    assert metrics["rate_error"] == 0.0


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


def test_store_exposes_no_active_mutation_after_bootstrap(temp_store):
    temp_store.ensure_bootstrap({"DEFAULT": {"small": (-0.3, 1.0)}})
    assert not hasattr(temp_store, "commit")
    assert not hasattr(temp_store, "rollback")
    assert not hasattr(temp_store, "_commit_authorized")
    assert not hasattr(temp_store, "_rollback_authorized")
    assert temp_store.load_active().version_id == BOOTSTRAP_VERSION_ID


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


def test_save_candidate_is_atomic_and_keeps_active(temp_store):
    temp_store.ensure_bootstrap({"DEFAULT": {"small": (-0.3, 1.0)}})
    candidate = StrategyVersion(
        version_id="v_candidate",
        created_at="2026-01-01T00:00:00",
        params={"DEFAULT": {"small": [0.0, 1.0]}},
        parent_version=BOOTSTRAP_VERSION_ID,
    )

    temp_store.save_candidate(candidate)

    assert temp_store.load_active().version_id == BOOTSTRAP_VERSION_ID
    saved = temp_store.get(candidate.version_id)
    assert saved is not None and saved.status == "candidate"
    # atomic replace용 임시 파일이 성공 경로에 남지 않고 JSON도 완전해야 한다.
    assert not list(temp_store.base.rglob("*.tmp"))
    json.loads(temp_store._version_path(candidate.version_id).read_text(encoding="utf-8"))


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


def test_critical_ratio_includes_a_value():
    no_a = ReservedRatioModel.critical_ratio(-0.3, 1.0, 89.745)
    with_a = ReservedRatioModel.critical_ratio(-0.3, 1.0, 89.745, 0.10)

    assert with_a != no_a
    assert with_a == pytest.approx(
        0.10 + (1 - 0.003 - 0.10) * (90.745 / 89.745)
    )


# ── 데이터셋 ─────────────────────────────────────────────────
def test_data_fingerprint_stable(records):
    """같은 데이터는 같은 fingerprint."""
    fp1 = ds.data_fingerprint(records)
    fp2 = ds.data_fingerprint(records)
    assert fp1 == fp2
    assert ds.data_fingerprint(list(reversed(records))) == fp1
    # 한 건 빼면 다른 fingerprint
    fp3 = ds.data_fingerprint(records[:-1])
    assert fp3 != fp1


def test_data_fingerprint_tracks_values_source_and_revision(records):
    """ID가 같아도 학습값·원장·정정본이 바뀌면 재평가해야 한다."""
    original = records[0]
    base = ds.data_fingerprint([original])

    assert ds.data_fingerprint([
        replace(original, reserved_price=original.reserved_price + 10)
    ]) != base
    assert ds.data_fingerprint([replace(original, source="corrected_db")]) != base
    assert ds.data_fingerprint([
        replace(original, source_revision="revision-2")
    ]) != base
    assert ds.data_fingerprint([
        replace(
            original,
            outcome_observed_at=datetime(2026, 8, 13, tzinfo=timezone.utc),
            outcome_observation_source="opening_result_revision",
        )
    ]) != base


def test_bracket_boundaries():
    """금액대 경계값 검증."""
    assert ds.get_bracket(9_999_9999) == "small"
    assert ds.get_bracket(1e8) == "medium"
    assert ds.get_bracket(5e8) == "large"
    assert ds.get_bracket(1e9) == "xlarge"
    assert ds.get_bracket(5e9) == "xxlarge"


def test_static_records_apply_base_consistency_filter_and_report_stats(tmp_path):
    rows = [
        {
            "bid_no": "VALID-1",
            "open_date": "2025-01-01",
            "basic_price": 100_000_000,
            "reserved_price": 101_000_000,
            "winner_price": 90_000_000,
            "winner_rate": 89.1,
            "lower_limit_rate": 87.745,
            "bid_method": "적격심사제",
        },
        {
            "bid_no": "MISMATCH-1",
            "open_date": "2025-01-02",
            "basic_price": 100_000_000,
            "reserved_price": 110_000_000,
            "winner_price": 90_000_000,
            "winner_rate": 89.1,
            "lower_limit_rate": 87.745,
            "bid_method": "적격심사제",
        },
    ]
    (tmp_path / "opening_results_2025.json").write_text(
        json.dumps(rows), encoding="utf-8"
    )
    stats = ds.DatasetQualityStats()

    loaded = ds.load_records(
        year_range=(2025, 2026),
        data_dir=tmp_path,
        quality_stats=stats,
        enforce_base_consistency=True,
    )

    assert [record.bid_no for record in loaded] == ["VALID-1"]
    assert stats.total_seen == 2
    assert stats.included == 1
    assert stats.excluded_base_mismatch == 1


def test_temporal_split_is_disjoint_and_ordered():
    def record(year: int) -> ds.BidRecord:
        return ds.BidRecord(
            bid_no=f"BID-{year}",
            title="",
            org="",
            bid_method="적격심사제",
            basic_price=100_000_000,
            estimated_price=100_000_000,
            reserved_price=100_000_000,
            winner_price=90_000_000,
            winner_rate=90.0,
            lower_limit_rate=87.745,
            year=year,
        )

    split = ds.split_temporal_records(
        [record(0), record(2024), record(2025), record(2026), record(2027)]
    )

    assert [row.year for row in split.train] == [2024]
    assert [row.year for row in split.validation] == [2025]
    assert [row.year for row in split.sealed_holdout] == [2026]
    assert [row.year for row in split.excluded_out_of_window] == [0, 2027]


def test_temporal_split_excludes_late_corrections_and_preselected_sealed():
    def record(year: int, observed_at: datetime) -> ds.BidRecord:
        return ds.BidRecord(
            bid_no=f"OBS-{year}-{observed_at.month}",
            title="",
            org="",
            bid_method="적격심사제",
            basic_price=100_000_000,
            estimated_price=100_000_000,
            reserved_price=100_000_000,
            winner_price=90_000_000,
            winner_rate=90.0,
            lower_limit_rate=87.745,
            year=year,
            outcome_observed_at=observed_at,
            outcome_observation_source="fixture",
        )

    late_train = record(2024, datetime(2025, 2, 1, tzinfo=timezone.utc))
    late_validation = record(2025, datetime(2026, 2, 1, tzinfo=timezone.utc))
    preselected_sealed = record(
        2026, datetime(2025, 12, 31, tzinfo=timezone.utc)
    )
    split = ds.split_temporal_records(
        [late_train, late_validation, preselected_sealed],
        candidate_selected_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        require_known_observation=True,
    )

    assert split.train == []
    assert split.validation == []
    assert split.sealed_holdout == []
    assert split.excluded_observed_after_cutoff == [
        late_train,
        late_validation,
    ]
    assert split.excluded_sealed_before_selection == [preselected_sealed]


def test_temporal_split_unknown_observation_fails_closed_when_required():
    record = ds.BidRecord(
        bid_no="OBS-UNKNOWN",
        title="",
        org="",
        bid_method="적격심사제",
        basic_price=100_000_000,
        estimated_price=100_000_000,
        reserved_price=100_000_000,
        winner_price=90_000_000,
        winner_rate=90.0,
        lower_limit_rate=87.745,
        year=2024,
    )

    split = ds.split_temporal_records(
        [record], require_known_observation=True
    )

    assert split.train == []
    assert split.excluded_observation_unknown == [record]


def test_static_observation_requires_explicit_collection_timestamp(tmp_path):
    base = {
        "open_date": "2024-06-01T10:00:00+09:00",
        "basic_price": 100_000_000,
        "reserved_price": 100_500_000,
        "winner_price": 90_000_000,
        "winner_rate": 89.55,
        "lower_limit_rate": 87.745,
        "bid_method": "적격심사제",
    }
    rows = [
        {**base, "bid_no": "OBS-OPEN-DATE-ONLY"},
        {
            **base,
            "bid_no": "OBS-EXPLICIT",
            "crawled_at": "2024-06-02T01:00:00Z",
        },
    ]
    (tmp_path / "opening_results_2024.json").write_text(
        json.dumps(rows), encoding="utf-8"
    )
    stats = ds.DatasetQualityStats()

    loaded = ds.load_records(
        year_range=(2024, 2025),
        data_dir=tmp_path,
        quality_stats=stats,
        require_observation_time=True,
    )

    assert [record.bid_no for record in loaded] == ["OBS-EXPLICIT"]
    assert loaded[0].outcome_observed_at == datetime(
        2024, 6, 2, 1, tzinfo=timezone.utc
    )
    assert loaded[0].outcome_observation_source == "static:crawled_at"
    assert stats.excluded_observation_time_unknown == 1


def test_guard_blocks_promotion_when_sealed_sample_is_too_small(records):
    validation = [row for row in records if row.year == 2025]
    sealed = validation[:3]

    decision = guard.evaluate_candidate(
        BID_STRATEGY,
        BID_STRATEGY,
        validation,
        holdout_records=sealed,
        min_validation_samples=1,
        min_holdout_samples=4,
    )

    assert not decision.accepted
    assert decision.sample_counts == {"validation": len(validation), "sealed_holdout": 3}
    assert any("sealed holdout 표본 부족" in reason for reason in decision.reasons)


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
    assert len(merged) > len(static_only)
    assert any(r.bid_no == "OPRTEST-1" for r in merged)
    # 무효 데이터(가격 0)는 제외
    assert all(r.basic_price > 0 and r.winner_price > 0 for r in merged)


def test_db_record_uses_latest_authoritative_revision_observation(
    db_session, tmp_path
):
    """정정된 과거 outcome은 open_date가 아닌 최신 revision 관측시각을 쓴다."""
    from app.db import models

    crawler_time = datetime(2026, 7, 1, tzinfo=timezone.utc)
    correction_time = datetime(2026, 8, 1, tzinfo=timezone.utc)
    db_session.add_all([
        models.OpeningResult(
            bid_no="OBS-REVISION-1",
            organization="A기관",
            bid_method="적격심사제",
            open_date=datetime(2024, 6, 1),
            basic_price=100_000_000,
            reserved_price=100_500_000,
            winner_price=90_000_000,
            winner_rate=89.55,
            crawled_at=crawler_time,
        ),
        models.RawSourceSnapshot(
            snapshot_hash="snapshot-observation-revision-1",
            source_type="opening_result_api",
            source_uri="fixture://opening/OBS-REVISION-1",
            captured_at=correction_time,
            as_of_cutoff=correction_time,
            artifact_hash="artifact-observation-revision-1",
            raw_payload={"bid_no": "OBS-REVISION-1"},
        ),
    ])
    db_session.flush()
    db_session.add(models.OpeningResultRevision(
        id="opening-revision-observation-1",
        bid_no="OBS-REVISION-1",
        revision_no=2,
        source_snapshot_hash="snapshot-observation-revision-1",
        content_hash="content-observation-revision-1",
        payload={"winner_price": 90_000_000},
        observed_at=correction_time,
        created_at=correction_time,
    ))
    db_session.flush()

    record = next(
        item
        for item in ds.load_records(
            data_dir=tmp_path,
            db=db_session,
            require_observation_time=True,
        )
        if item.bid_no == "OBS-REVISION-1"
    )

    assert record.outcome_observed_at == correction_time
    assert record.outcome_observation_source == "opening_result_revision"
    assert "opening:2:content-observation-revision-1" in record.source_revision


def test_latest_db_revision_supersedes_older_static_export(db_session, tmp_path):
    """파일 로드 순서가 DB의 더 최신 append-only 정정을 가리지 않는다."""
    from app.db import models

    (tmp_path / "opening_results_2024.json").write_text(
        json.dumps([{
            "bid_no": "OBS-SUPERSEDES-1",
            "open_date": "2024-06-01",
            "crawled_at": "2024-06-02T00:00:00Z",
            "basic_price": 100_000_000,
            "reserved_price": 100_000_000,
            "winner_price": 89_000_000,
            "winner_rate": 89.0,
            "lower_limit_rate": 87.745,
            "bid_method": "적격심사제",
        }]),
        encoding="utf-8",
    )
    corrected_at = datetime(2024, 7, 1, tzinfo=timezone.utc)
    db_session.add_all([
        models.OpeningResult(
            bid_no="OBS-SUPERSEDES-1",
            organization="A기관",
            bid_method="적격심사제",
            open_date=datetime(2024, 6, 1),
            basic_price=100_000_000,
            reserved_price=100_500_000,
            winner_price=90_000_000,
            winner_rate=89.55,
            crawled_at=corrected_at,
        ),
        models.RawSourceSnapshot(
            snapshot_hash="snapshot-observation-supersedes-1",
            source_type="opening_result_api",
            source_uri="fixture://opening/OBS-SUPERSEDES-1",
            captured_at=corrected_at,
            as_of_cutoff=corrected_at,
            artifact_hash="artifact-observation-supersedes-1",
            raw_payload={"bid_no": "OBS-SUPERSEDES-1"},
        ),
    ])
    db_session.flush()
    db_session.add(models.OpeningResultRevision(
        id="opening-revision-supersedes-1",
        bid_no="OBS-SUPERSEDES-1",
        revision_no=2,
        source_snapshot_hash="snapshot-observation-supersedes-1",
        content_hash="content-observation-supersedes-1",
        payload={"winner_price": 90_000_000},
        observed_at=corrected_at,
        created_at=corrected_at,
    ))
    db_session.flush()

    records = ds.load_records(
        year_range=(2024, 2025),
        data_dir=tmp_path,
        db=db_session,
        require_observation_time=True,
    )
    matches = [
        record for record in records if record.bid_no == "OBS-SUPERSEDES-1"
    ]

    assert len(matches) == 1
    assert matches[0].source == "opening_results_db"
    assert matches[0].winner_price == 90_000_000
    assert matches[0].outcome_observed_at == corrected_at


def test_db_records_apply_base_consistency_filter_and_report_stats(
    db_session, tmp_path
):
    """DB 누적분도 mock/benchmark와 같은 0.94~1.06 계약을 쓴다."""
    from datetime import datetime
    from app.db import models

    db_session.add_all([
        models.OpeningResult(
            bid_no="DB-VALID-1",
            organization="A기관",
            bid_method="적격심사제",
            open_date=datetime(2026, 6, 1),
            basic_price=100_000_000,
            reserved_price=101_000_000,
            winner_price=90_000_000,
            winner_rate=89.1,
        ),
        models.OpeningResult(
            bid_no="DB-MISMATCH-1",
            organization="A기관",
            bid_method="적격심사제",
            open_date=datetime(2026, 6, 1),
            basic_price=100_000_000,
            reserved_price=110_000_000,
            winner_price=90_000_000,
            winner_rate=89.1,
        ),
    ])
    db_session.flush()
    stats = ds.DatasetQualityStats()

    loaded = ds.load_records(
        data_dir=tmp_path,
        db=db_session,
        quality_stats=stats,
        enforce_base_consistency=True,
    )

    loaded_ids = {record.bid_no for record in loaded}
    assert "DB-VALID-1" in loaded_ids
    assert "DB-MISMATCH-1" not in loaded_ids
    assert stats.total_seen >= 2
    assert stats.included >= 1
    # 테스트 DB는 session scope이고 다른 개찰 fixture가 commit될 수 있다. 최소
    # 이 fixture의 mismatch가 집계됐음을 확인한다.
    assert stats.excluded_base_mismatch >= 1


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


def test_db_records_join_notice_a_value_and_status(db_session, tmp_path):
    """OpeningResult에 없는 A값은 같은 공고 Notice 원장에서 결합한다."""
    from datetime import datetime
    from app.db import models

    db_session.add_all([
        models.Notice(
            bid_no="ATEST-1",
            title="A값 결합",
            basic_price=100_000_000,
            basis_amount=100_000_000,
            a_value=7_654_321,
            a_value_source="tier0",
            a_value_applicable="Y",
            contract_type="CONSTRUCTION",
        ),
        models.OpeningResult(
            bid_no="ATEST-1",
            organization="A기관",
            bid_method="적격심사제",
            open_date=datetime(2026, 6, 1),
            basic_price=100_000_000,
            reserved_price=100_500_000,
            winner_price=90_000_000,
            winner_rate=89.55,
        ),
    ])
    db_session.flush()

    records = ds.load_records(
        data_dir=tmp_path,
        db=db_session,
        enforce_base_consistency=True,
        require_a_value_status=True,
    )

    record = next(item for item in records if item.bid_no == "ATEST-1")
    assert record.a_value == 7_654_321
    assert record.a_value_status == "confirmed"
    assert "a:tier0:Y" in record.source_revision


def test_training_excludes_unknown_a_value_status(db_session, tmp_path):
    """A값 미적용인지 결측인지 모르는 행은 자가보정 학습에 들어가지 않는다."""
    from datetime import datetime
    from app.db import models

    db_session.add(models.OpeningResult(
        bid_no="ATEST-UNKNOWN",
        organization="A기관",
        bid_method="적격심사제",
        open_date=datetime(2026, 6, 1),
        basic_price=100_000_000,
        reserved_price=100_500_000,
        winner_price=90_000_000,
        winner_rate=89.55,
    ))
    db_session.flush()
    stats = ds.DatasetQualityStats()

    records = ds.load_records(
        data_dir=tmp_path,
        db=db_session,
        quality_stats=stats,
        enforce_base_consistency=True,
        require_a_value_status=True,
    )

    assert all(item.bid_no != "ATEST-UNKNOWN" for item in records)
    assert stats.excluded_a_value_unknown >= 1


def test_training_uses_only_predeadline_notice_features(db_session, tmp_path):
    """개찰 후 projection 값으로 운영에서 불가능한 추천을 재구성하지 않는다."""
    from app.db import models

    notice_at = datetime(2024, 5, 1, tzinfo=timezone.utc)
    basis_at = datetime(2024, 5, 2, tzinfo=timezone.utc)
    deadline = datetime(2024, 5, 10, tzinfo=timezone.utc)
    observed = datetime(2024, 5, 11, tzinfo=timezone.utc)
    db_session.add_all([
        models.Notice(
            bid_no="FEATURE-LINEAGE-VALID",
            title="추천시점 feature 정본",
            basic_price=90_000_000,  # 추정가격: 학습 기초금액으로 쓰면 안 됨
            basis_amount=100_000_000,
            basis_amount_at=basis_at,
            start_date=notice_at,
            end_date=deadline,
            bid_method="적격심사제",
            lower_limit_rate=89.745,
            contract_type="CONSTRUCTION",
            a_value=0,
            a_value_source="tier0",
            a_value_applicable="N",
        ),
        models.OpeningResult(
            bid_no="FEATURE-LINEAGE-VALID",
            organization="A기관",
            bid_method="사후결과의다른방식",
            open_date=deadline,
            basic_price=90_000_000,
            reserved_price=100_500_000,
            winner_price=90_000_000,
            winner_rate=89.55,
            lower_limit_rate=60.0,
            crawled_at=observed,
        ),
        models.Notice(
            bid_no="FEATURE-LINEAGE-LATE",
            title="마감 후 공개된 기초금액",
            basic_price=90_000_000,
            basis_amount=100_000_000,
            basis_amount_at=datetime(2024, 5, 12, tzinfo=timezone.utc),
            start_date=notice_at,
            end_date=deadline,
            bid_method="적격심사제",
            lower_limit_rate=89.745,
            contract_type="CONSTRUCTION",
            a_value=0,
            a_value_source="tier0",
            a_value_applicable="N",
        ),
        models.OpeningResult(
            bid_no="FEATURE-LINEAGE-LATE",
            organization="A기관",
            bid_method="적격심사제",
            open_date=deadline,
            basic_price=100_000_000,
            reserved_price=100_500_000,
            winner_price=90_000_000,
            winner_rate=89.55,
            lower_limit_rate=89.745,
            crawled_at=observed,
        ),
    ])
    db_session.flush()
    stats = ds.DatasetQualityStats()

    records = ds.load_records(
        year_range=(2024, 2025),
        data_dir=tmp_path,
        db=db_session,
        quality_stats=stats,
        enforce_base_consistency=True,
        require_a_value_status=True,
        require_observation_time=True,
        require_feature_lineage=True,
    )

    record = next(row for row in records if row.bid_no == "FEATURE-LINEAGE-VALID")
    assert record.basic_price == 100_000_000
    assert record.bid_method == "적격심사제"
    assert record.lower_limit_rate == 89.745
    assert record.feature_observed_at == basis_at
    assert record.feature_cutoff_at == deadline
    assert all(row.bid_no != "FEATURE-LINEAGE-LATE" for row in records)
    assert stats.excluded_feature_observed_after_cutoff >= 1


def test_excluded_static_row_does_not_mask_corrected_db_record(
    db_session, tmp_path
):
    """A 상태 없는 정적본보다 Notice와 결합된 DB 정정본을 우선 포함한다."""
    from datetime import datetime
    from app.db import models

    (tmp_path / "opening_results_2026.json").write_text(
        json.dumps([{
            "bid_no": "A-CORRECTED",
            "open_date": "2026-06-01",
            "basic_price": 100_000_000,
            "reserved_price": 100_500_000,
            "winner_price": 90_000_000,
            "winner_rate": 89.55,
            "lower_limit_rate": 89.745,
            "bid_method": "적격심사제",
        }]),
        encoding="utf-8",
    )
    db_session.add_all([
        models.Notice(
            bid_no="A-CORRECTED",
            title="DB A값 정정",
            basic_price=100_000_000,
            basis_amount=100_000_000,
            a_value=5_000_000,
            a_value_source="tier0",
            a_value_applicable="Y",
            contract_type="CONSTRUCTION",
        ),
        models.OpeningResult(
            bid_no="A-CORRECTED",
            organization="A기관",
            bid_method="적격심사제",
            open_date=datetime(2026, 6, 1),
            basic_price=100_000_000,
            reserved_price=100_500_000,
            winner_price=90_000_000,
            winner_rate=89.55,
            lower_limit_rate=89.745,
        ),
    ])
    db_session.flush()

    records = ds.load_records(
        year_range=(2026, 2027),
        data_dir=tmp_path,
        db=db_session,
        enforce_base_consistency=True,
        require_a_value_status=True,
    )

    matches = [item for item in records if item.bid_no == "A-CORRECTED"]
    assert len(matches) == 1
    assert matches[0].source == "opening_results_db"
    assert matches[0].a_value == 5_000_000


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


# ── 승격 루프 ───────────────────────────────────────────────
def _cycle_records() -> list[ds.BidRecord]:
    observed_by_year = {
        2024: datetime(2024, 12, 31, tzinfo=timezone.utc),
        2025: datetime(2025, 12, 31, tzinfo=timezone.utc),
        2026: datetime(2026, 2, 1, tzinfo=timezone.utc),
    }
    return [
        ds.BidRecord(
            bid_no=f"CYCLE-{year}",
            title="",
            org="A기관",
            bid_method="소액수의견적",
            basic_price=100_000_000,
            estimated_price=100_000_000,
            reserved_price=100_000_000,
            winner_price=90_000_000,
            winner_rate=90.0,
            lower_limit_rate=87.745,
            year=year,
            a_value_status="not_applicable",
            source="fixture",
            source_revision="1",
            outcome_observed_at=observed_by_year[year],
            outcome_observation_source="fixture",
        )
        for year in (2024, 2025, 2026)
    ]


def test_cycle_default_saves_candidate_without_promoting(
    temp_store, monkeypatch
):
    """기존/주간 호출의 기본값은 가드가 통과해도 active를 바꾸지 않는다."""
    from app.services.autocalibrate import loop

    monkeypatch.setattr(loop, "get_default_store", lambda: temp_store)
    monkeypatch.setattr(loop.ds, "load_records", lambda **_: _cycle_records())

    report = loop.run_calibration_cycle(
        trigger="manual",
        min_train_samples=1,
        min_validation_samples=1,
    )

    assert report.decision is not None and report.decision.accepted
    assert report.candidate_saved
    assert not report.adopted
    assert report.gate_decision == "NOT_EVALUATED"
    assert temp_store.load_active().version_id == BOOTSTRAP_VERSION_ID
    assert temp_store.get(report.candidate_version).status == "candidate"


def test_cycle_optimizes_train_only_and_does_not_open_sealed_test(
    temp_store, monkeypatch
):
    """2025 validation/2026 sealed가 후보 최적화 입력으로 새지 않는다."""
    from app.services.autocalibrate import loop

    seen_years: list[int] = []

    def optimize_train_only(records, _risk_model, baseline, _weights, **_kwargs):
        seen_years.extend(record.year for record in records)
        return baseline

    monkeypatch.setattr(loop, "get_default_store", lambda: temp_store)
    monkeypatch.setattr(loop.ds, "load_records", lambda **_: _cycle_records())
    monkeypatch.setattr(loop.optimizer, "optimize_all", optimize_train_only)

    report = loop.run_calibration_cycle(
        trigger="manual",
        min_train_samples=1,
        min_validation_samples=1,
    )

    assert seen_years == [2024]
    assert report.temporal_counts == {
        "train": 1,
        "validation": 1,
        "sealed_holdout": 0,
        "excluded_out_of_window": 0,
        "excluded_observation_unknown": 0,
        "excluded_observed_after_cutoff": 0,
        "excluded_sealed_before_selection": 1,
    }
    assert report.decision is not None and report.decision.accepted
    assert report.decision.sample_counts["sealed_holdout"] == 0
    assert report.decision.holdout_metrics == {}
    assert report.candidate_saved
    saved = temp_store.get(report.candidate_version)
    assert saved.data_fingerprint == ds.data_fingerprint(_cycle_records()[:2])
    assert saved.metrics["sealed_holdout"] == {
        "status": "SEALED_NOT_OPENED",
        "count": 0,
    }
    assert temp_store.load_active().version_id == BOOTSTRAP_VERSION_ID
    assert saved.status == "candidate"


def test_cycle_requires_observation_lineage_and_excludes_late_train_correction(
    temp_store, monkeypatch
):
    from app.services.autocalibrate import loop

    records = _cycle_records()
    late_correction = replace(
        records[0],
        bid_no="CYCLE-2024-LATE-CORRECTION",
        outcome_observed_at=datetime(2025, 2, 1, tzinfo=timezone.utc),
        source_revision="corrected-after-training-cutoff",
    )
    loader_kwargs = {}
    optimized_bid_nos: list[str] = []

    def load_with_lineage_contract(**kwargs):
        loader_kwargs.update(kwargs)
        return [*records, late_correction]

    def optimize_train_only(rows, _risk_model, baseline, _weights, **_kwargs):
        optimized_bid_nos.extend(row.bid_no for row in rows)
        return baseline

    monkeypatch.setattr(loop, "get_default_store", lambda: temp_store)
    monkeypatch.setattr(loop.ds, "load_records", load_with_lineage_contract)
    monkeypatch.setattr(loop.optimizer, "optimize_all", optimize_train_only)

    report = loop.run_calibration_cycle(
        trigger="manual",
        min_train_samples=1,
        min_validation_samples=1,
    )

    assert loader_kwargs["require_observation_time"] is True
    assert loader_kwargs["require_feature_lineage"] is True
    assert loader_kwargs["year_range"] == (2021, 2026)
    assert optimized_bid_nos == ["CYCLE-2024"]
    assert report.temporal_counts["excluded_observed_after_cutoff"] == 1


def test_cycle_rejects_legacy_inline_promotion_arguments(
    temp_store, monkeypatch
):
    from app.services.autocalibrate import loop

    monkeypatch.setattr(loop, "get_default_store", lambda: temp_store)
    monkeypatch.setattr(loop.ds, "load_records", lambda **_: _cycle_records())

    with pytest.raises(PromotionAuthorizationError, match="인라인 승격"):
        loop.run_calibration_cycle(
            trigger="manual",
            gate_decision="PASS",
            approval_id="human-review-20260813",
            min_train_samples=1,
            min_validation_samples=1,
        )

    assert not temp_store.active_file.exists()


def test_candidate_fingerprint_prevents_duplicate_scheduled_evaluation(
    temp_store, monkeypatch
):
    from app.services.autocalibrate import loop

    records = _cycle_records()
    fingerprint = ds.data_fingerprint(records)
    temp_store.ensure_bootstrap(BID_STRATEGY)
    temp_store.save_candidate(StrategyVersion(
        version_id="v_already_evaluated",
        created_at="2026-08-13T00:00:00",
        params=BID_STRATEGY,
        parent_version=BOOTSTRAP_VERSION_ID,
        data_fingerprint=fingerprint,
    ))
    monkeypatch.setattr(loop, "get_default_store", lambda: temp_store)

    assert loop.should_recalibrate(records) is False
    assert loop.should_recalibrate([
        replace(records[0], reserved_price=records[0].reserved_price + 10),
        *records[1:],
    ]) is True


def test_scheduled_task_explicitly_disables_promotion(monkeypatch):
    """beat 진입점은 PASS나 승인 ID를 주입할 수 없는 후보 평가 전용이다."""
    from app.services.autocalibrate import loop
    from app.tasks import calibration_tasks
    from app.db import session as db_session_module

    called = {}

    class FakeDb:
        def close(self):
            called["closed"] = True

    def fake_cycle(**kwargs):
        called.update(kwargs)
        return SimpleNamespace(summary=lambda: "candidate", adopted=False)

    monkeypatch.setattr(loop, "run_calibration_cycle", fake_cycle)
    monkeypatch.setattr(db_session_module, "SessionLocal", FakeDb)

    result = calibration_tasks.recalibrate_strategy.run()

    assert result == "candidate"
    assert called["trigger"] == "scheduled"
    assert "gate_decision" not in called
    assert "approval_id" not in called
    assert called["closed"] is True
