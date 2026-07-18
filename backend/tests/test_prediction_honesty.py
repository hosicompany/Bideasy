"""
/prediction/{bid_no}/recommend-points 정직성 회귀 테스트
=========================================================
2026-07-17 수습: 합성(Demo Mode) 데이터 생성 경로 제거 검증.
- 실데이터 없으면 명시적 insufficient_data (가짜 통계 금지)
- 실데이터 있으면 실측 기술통계만
- 응답 골격(키 구성)은 기존 클라이언트와 호환 유지
"""

from datetime import datetime

from app.db import models


def _make_notice(db, bid_no="T2026-PRED-01", org="정직테스트발주기관"):
    notice = models.Notice(
        bid_no=bid_no,
        title="정직성 테스트 공고",
        basic_price=100_000_000.0,
        contract_type="CONSTRUCTION",
        organization=org,
        region="서울",
        bid_method="적격심사제",
    )
    db.add(notice)
    db.commit()
    return notice


def _add_opening_results(db, org, n=6, base_rate=87.80, participants=120):
    for i in range(n):
        db.add(models.OpeningResult(
            bid_no=f"OR-{org}-{i}",
            organization=org,
            region="서울",
            open_date=datetime(2025, 1, 1 + i),
            basic_price=100_000_000.0,
            reserved_price=100_500_000.0,
            bid_method="적격심사제",
            winner_company=f"업체{i}",
            winner_price=87_800_000.0 + i * 10_000,
            winner_rate=base_rate + i * 0.01,
            participants_count=participants + i,
        ))
    db.commit()


def test_unknown_bid_no_returns_message(client):
    res = client.get("/api/v1/prediction/UNKNOWN-BID/recommend-points")
    assert res.status_code == 200
    body = res.json()
    assert body["strategies"] == []
    assert "찾을 수 없습니다" in body["message"]


def test_no_data_returns_insufficient_not_synthetic(client, db_session):
    """실데이터가 없으면 합성 통계를 만들지 않고 insufficient_data 를 명시한다."""
    _make_notice(db_session, bid_no="T2026-PRED-01", org="데이터없는기관XYZ")

    res = client.get("/api/v1/prediction/T2026-PRED-01/recommend-points")
    assert res.status_code == 200
    body = res.json()

    # 응답 골격 유지 (Flutter 호환)
    for key in ("agency_profile", "monte_carlo", "blue_ocean", "competition", "qualification"):
        assert key in body

    # 기관 통계: 합성값 대신 명시적 부족 표시
    profile = body["agency_profile"]
    assert profile["status"] == "insufficient_data"
    assert profile["sample_size"] == 0
    assert "avg_rate" not in profile  # 과거 합성 필드가 생성되지 않아야 함

    # 분포 요약: 가짜 구간 없음
    assert body["monte_carlo"]["top_rates"] == []
    # 블루오션: 랜덤 생성 문구 제거
    assert body["blue_ocean"]["strategies"] == []
    # 경쟁: 하드코딩 배수·랜덤 노이즈 기반 predicted_count 생성 금지
    comp = body["competition"]
    assert comp["status"] == "insufficient_data"
    assert comp["predicted_count"] == 0


def test_real_data_returns_facts_deterministically(client, db_session):
    """실데이터가 충분하면 실측 기술통계를 반환하고, 반복 호출이 결정적이어야 한다."""
    org = "데이터있는기관ABC"
    _make_notice(db_session, bid_no="T2026-PRED-02", org=org)
    _add_opening_results(db_session, org, n=6, base_rate=87.80, participants=120)

    res1 = client.get("/api/v1/prediction/T2026-PRED-02/recommend-points")
    res2 = client.get("/api/v1/prediction/T2026-PRED-02/recommend-points")
    assert res1.status_code == 200
    b1, b2 = res1.json(), res2.json()

    profile = b1["agency_profile"]
    assert profile["status"] == "ok"
    assert profile["sample_size"] == 6
    assert 87.79 < profile["avg_rate"] < 87.90  # 실측 평균 (87.80~87.85)

    # 분위수 요약: 5개 값, 결정적 (랜덤 없음 — 두 호출 동일)
    assert len(b1["monte_carlo"]["top_rates"]) == 5
    assert b1["monte_carlo"]["top_rates"] == b2["monte_carlo"]["top_rates"]

    # 경쟁: 실측 평균 참가 수 (120~125 평균 ≈ 122~123)
    comp = b1["competition"]
    assert comp["status"] == "ok"
    assert comp["basis"] == "historical_avg"
    assert 120 <= comp["predicted_count"] <= 126
    assert comp["sample_size"] == 6
