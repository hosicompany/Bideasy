"""누적 개찰 통계(S1) — 집계 계약 검증.

⚠️ 이 파일의 테스트는 `rebuild()` 가 commit 하므로 파일 DB 에 행을 남긴다.
`db_session` fixture 는 rollback 만 하므로 **명시적으로 지운다**(안 지우면 뒤
파일의 테스트가 남은 행을 본다 — 실제로 겪은 함정).
"""
from datetime import datetime, timedelta

import pytest

from app.db import models
from app.services import opening_stats as os_svc
from app.services.lower_limits import amount_band_label, get_amount_band


@pytest.fixture
def clean_stats(db_session):
    """개찰 원장·통계를 비운 상태로 시작하고, 끝나면 되돌린다."""
    def _wipe():
        db_session.query(models.OpeningStat).delete()
        db_session.query(models.OpeningResult).delete()
        db_session.commit()

    _wipe()
    yield db_session
    _wipe()


def _result(bid_no, *, org="발주기관A", method="적격심사제",
            basic=200_000_000, reserved_ratio=1.0, winner_rate=0.90,
            participants=None, days_ago=10):
    return models.OpeningResult(
        bid_no=bid_no,
        organization=org,
        bid_method=method,
        open_date=datetime.utcnow() - timedelta(days=days_ago),
        basic_price=basic,
        reserved_price=basic * reserved_ratio,
        winner_price=basic * winner_rate,
        participants_count=participants,
    )


# ---------------------------------------------------------------- 금액대 밴드

def test_amount_band_uses_lower_limit_boundaries():
    """밴드 경계 = 낙찰하한율이 바뀌는 지점. 따로 정의하면 두 소스가 갈라진다."""
    assert get_amount_band(299_999_999) == "LT_3E"
    assert get_amount_band(300_000_000) == "3E_10E"
    assert get_amount_band(999_999_999) == "3E_10E"
    assert get_amount_band(1_000_000_000) == "10E_50E"
    assert get_amount_band(5_000_000_000) == "50E_100E"
    assert get_amount_band(10_000_000_000) == "GE_100E"


def test_amount_band_unknown_amount_is_empty():
    """금액을 모르면 밴드도 없다 — 임의로 최저 밴드에 밀어 넣지 않는다."""
    assert get_amount_band(None) == ""
    assert get_amount_band(0) == ""
    assert get_amount_band(-1) == ""


def test_amount_band_label_roundtrip():
    assert amount_band_label("LT_3E") == "3억 미만"
    assert amount_band_label("모르는코드") == "모르는코드"


# ---------------------------------------------------------------- 드리프트 가드

def test_ratio_guard_matches_arm_backtest():
    """기준 일치 검사 범위가 백테스트 쪽과 갈라지면 두 곳의 판정이 달라진다."""
    from app.services import arm_backtest

    assert os_svc.RATIO_MIN == arm_backtest.BASE_RATIO_MIN
    assert os_svc.RATIO_MAX == arm_backtest.BASE_RATIO_MAX


def test_no_mean_columns_on_stat_model():
    """평균을 담지 않는다는 계약(§2) — 사정률 평균은 전 기관 100% 근처라 신호가 없다.

    담아 두면 언젠가 화면이 "이 기관 사정률은 99.84%" 로 읽어 예측처럼 보인다.
    """
    cols = set(models.OpeningStat.__table__.columns.keys())
    assert not [c for c in cols if "avg" in c or "mean" in c]


# ---------------------------------------------------------------- 집계

def test_rebuild_skips_cells_below_min_sample(clean_stats):
    """n < MIN_SAMPLE 은 저장하지 않고, 버린 셀 수를 보고한다(조용한 절삭 금지)."""
    db = clean_stats
    for i in range(os_svc.MIN_SAMPLE - 1):
        db.add(_result(f"SMALL-{i}"))
    db.commit()

    r = os_svc.rebuild(db)

    assert r["cells_written"] == 0
    assert r["cells_skipped_small"] >= 1   # 기관 셀 + 기관 무관 셀
    assert db.query(models.OpeningStat).count() == 0


def test_rebuild_writes_org_and_all_orgs_cells(clean_stats):
    """기관 무관 셀은 항상 만든다 — 기관 표본이 모자랄 때 물러설 자리."""
    db = clean_stats
    for i in range(os_svc.MIN_SAMPLE):
        db.add(_result(f"OK-{i}", org="발주기관A"))
    db.commit()

    os_svc.rebuild(db)

    orgs = {s.organization for s in db.query(models.OpeningStat).all()}
    assert orgs == {"발주기관A", os_svc.ALL_ORGS}


def test_rebuild_excludes_base_mismatch_and_counts_it(clean_stats):
    """기초금액과 예정가격의 기준이 어긋난 행은 표본에서 뺀다 — 세어서 보고한다.

    `basic_price` 에 추정가격이 섞여 있던 사고의 후속 방어
    (docs/PRICE_BASE_DEFECT.md). 한 행이 분위수를 통째로 민다.
    """
    db = clean_stats
    for i in range(os_svc.MIN_SAMPLE):
        db.add(_result(f"GOOD-{i}"))
    # 사정률 1.10 — 예정가격은 기초금액 ±3% 안이어야 하므로 구조적으로 불가능
    for i in range(5):
        db.add(_result(f"BAD-{i}", reserved_ratio=1.10))
    db.commit()

    r = os_svc.rebuild(db)

    assert r["excluded_base_mismatch"] == 5
    cell = db.query(models.OpeningStat).filter(
        models.OpeningStat.organization == os_svc.ALL_ORGS).one()
    assert cell.n == os_svc.MIN_SAMPLE


def test_rebuild_percentiles(clean_stats):
    """분위수가 표본을 그대로 반영하는가."""
    db = clean_stats
    # 낙찰 투찰률 88.0 ~ 97.0 % (10건, 1%p 간격)
    for i in range(10):
        db.add(_result(f"P-{i}", winner_rate=0.88 + i * 0.01))
    db.commit()

    os_svc.rebuild(db)

    cell = db.query(models.OpeningStat).filter(
        models.OpeningStat.organization == os_svc.ALL_ORGS).one()
    assert cell.n == 10
    assert cell.winner_rate_p10 == pytest.approx(89.0, abs=0.01)
    assert cell.winner_rate_p50 == pytest.approx(92.0, abs=0.51)
    assert cell.winner_rate_p90 == pytest.approx(96.0, abs=0.01)


def test_rebuild_participants_ignores_missing(clean_stats):
    """참여사수는 아는 표본만 센다 — 결측을 0 으로 세면 경쟁이 없어 보인다."""
    db = clean_stats
    for i in range(6):
        db.add(_result(f"PC-{i}", participants=10 + i))
    for i in range(6):
        db.add(_result(f"PN-{i}", participants=None))
    db.commit()

    os_svc.rebuild(db)

    cell = db.query(models.OpeningStat).filter(
        models.OpeningStat.organization == os_svc.ALL_ORGS).one()
    assert cell.n == 12
    assert cell.participants_n == 6
    assert cell.participants_max == 15
    assert cell.participants_p50 is not None


def test_rebuild_ignores_rows_outside_window(clean_stats):
    db = clean_stats
    for i in range(os_svc.MIN_SAMPLE):
        db.add(_result(f"OLD-{i}", days_ago=400))
    db.commit()

    r = os_svc.rebuild(db, window_days=365)

    assert r["scanned"] == 0
    assert r["cells_written"] == 0


def test_rebuild_is_idempotent(clean_stats):
    """두 번 돌려도 행이 늘지 않는다 — 재집계는 갈아끼우기다."""
    db = clean_stats
    for i in range(os_svc.MIN_SAMPLE):
        db.add(_result(f"IDEM-{i}"))
    db.commit()

    first = os_svc.rebuild(db)
    second = os_svc.rebuild(db)

    assert first["cells_written"] == second["cells_written"]
    assert db.query(models.OpeningStat).count() == second["cells_written"]


# ---------------------------------------------------------------- 조회

def test_lookup_prefers_org_then_falls_back(clean_stats):
    db = clean_stats
    for i in range(os_svc.MIN_SAMPLE):
        db.add(_result(f"A-{i}", org="발주기관A"))
    db.commit()
    os_svc.rebuild(db)

    hit = os_svc.lookup(db, "적격심사제", 200_000_000, organization="발주기관A")
    assert hit is not None and hit.organization == "발주기관A"

    # 표본이 없는 기관 → 기관 무관 셀로 물러선다
    fallback = os_svc.lookup(db, "적격심사제", 200_000_000, organization="없는기관")
    assert fallback is not None and fallback.organization == os_svc.ALL_ORGS


def test_lookup_does_not_substitute_other_band(clean_stats):
    """근처 셀을 대신 주지 않는다 — 다른 게임의 숫자를 이 공고 숫자처럼 보이게 한다."""
    db = clean_stats
    for i in range(os_svc.MIN_SAMPLE):
        db.add(_result(f"B-{i}", basic=200_000_000))   # LT_3E
    db.commit()
    os_svc.rebuild(db)

    assert os_svc.lookup(db, "적격심사제", 5_000_000_000) is None   # 50E_100E
    assert os_svc.lookup(db, "최저가낙찰제", 200_000_000) is None    # 다른 방식
    assert os_svc.lookup(db, "적격심사제", None) is None            # 금액 미상
