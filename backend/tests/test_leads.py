"""Tests for 무료 자격 진단 리드 엔드포인트 (/api/v1/leads)."""
from datetime import datetime, timedelta

import pytest


def _mk_notice(db, bid_no, title, region, days=5):
    from app.db import models

    n = models.Notice(
        bid_no=bid_no,
        title=title,
        basic_price=100000000,
        contract_type="CONSTRUCTION",
        organization="테스트기관",
        region=region,
        start_date=datetime.now(),
        end_date=datetime.now() + timedelta(days=days),
    )
    db.add(n)
    return n


def _clear_notices(db):
    """세션 스코프 파일 DB — 커밋된 notices 가 테스트 간 남으므로 시딩 전 비운다."""
    from app.db import models

    db.query(models.Notice).delete()
    db.commit()


@pytest.fixture
def busan_electric_notices(db_session):
    """부산 전기공사 3건 + 서울 전기공사 1건(지역 불일치) + 부산 통신 1건(공종 다름)."""
    _clear_notices(db_session)
    _mk_notice(db_session, "BUSAN-E1", "부산 A초등학교 전기공사", "부산광역시")
    _mk_notice(db_session, "BUSAN-E2", "부산 B청사 전기공사", "부산광역시")
    _mk_notice(db_session, "BUSAN-E3", "부산 C체육관 전기공사", "부산광역시")
    _mk_notice(db_session, "SEOUL-E1", "서울 D청사 전기공사", "서울특별시")
    _mk_notice(db_session, "BUSAN-C1", "부산 E센터 정보통신공사", "부산광역시")
    db_session.commit()


class TestDiagnose:
    def test_requires_industry_or_license(self, client):
        resp = client.post("/api/v1/leads/diagnose", json={"region": "부산광역시"})
        assert resp.status_code == 400

    def test_requires_region(self, client):
        """region 없으면 지역제한 공고가 전부 FAIL → 오해성 0건 방지 위해 400."""
        resp = client.post("/api/v1/leads/diagnose", json={"industry": "전기공사"})
        assert resp.status_code == 400

    def test_matches_by_trade_and_region(self, client, busan_electric_notices):
        """부산 전기공사업자 → 부산 전기 3건만 매칭(서울/통신 제외)."""
        resp = client.post(
            "/api/v1/leads/diagnose",
            json={"industry": "전기공사", "region": "부산광역시"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["matched_count"] == 3
        assert len(data["preview"]) == 3
        assert data["locked_count"] == 0
        bid_nos = {c["bid_no"] for c in data["preview"]}
        assert bid_nos == {"BUSAN-E1", "BUSAN-E2", "BUSAN-E3"}

    def test_region_mismatch_excluded(self, client, busan_electric_notices):
        """서울 업자는 부산 지역제한 공고에서 제외된다."""
        resp = client.post(
            "/api/v1/leads/diagnose",
            json={"industry": "전기공사", "region": "서울특별시"},
        )
        assert resp.status_code == 200
        data = resp.json()
        # 서울 전기공사 1건만 매칭
        assert data["matched_count"] == 1
        assert data["preview"][0]["bid_no"] == "SEOUL-E1"

    def test_preview_caps_at_three(self, client, db_session):
        _clear_notices(db_session)
        for i in range(6):
            _mk_notice(db_session, f"MANY-{i}", f"부산 {i}공원 전기공사", "부산광역시")
        db_session.commit()
        resp = client.post(
            "/api/v1/leads/diagnose",
            json={"industry": "전기공사", "region": "부산광역시"},
        )
        data = resp.json()
        assert data["matched_count"] == 6
        assert len(data["preview"]) == 3
        assert data["locked_count"] == 3


class TestCapture:
    def test_requires_valid_contact(self, client, busan_electric_notices):
        resp = client.post(
            "/api/v1/leads/capture",
            json={"industry": "전기공사", "region": "부산광역시"},
        )
        assert resp.status_code == 400

    def test_rejects_bad_email(self, client, busan_electric_notices):
        resp = client.post(
            "/api/v1/leads/capture",
            json={"industry": "전기공사", "region": "부산광역시", "email": "notanemail"},
        )
        assert resp.status_code == 400

    def test_captures_lead_and_returns_full_list(self, client, db_session, busan_electric_notices):
        from app.db import models

        resp = client.post(
            "/api/v1/leads/capture",
            json={
                "industry": "전기공사",
                "region": "부산광역시",
                "email": "boss@company.com",
                "nurture_channel": "email",
                "utm_source": "naver",
                "utm_medium": "cpc",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["matched_count"] == 3
        assert len(data["notices"]) == 3

        lead = db_session.query(models.Lead).filter(models.Lead.id == data["lead_id"]).first()
        assert lead is not None
        assert lead.email == "boss@company.com"
        assert lead.industry == "전기공사"
        assert lead.region == "부산광역시"
        assert lead.matched_count == 3
        assert lead.nurture_channel == "email"
        assert lead.utm_source == "naver"
        assert lead.source == "web_diagnose"

    def test_phone_only_contact_ok(self, client, db_session, busan_electric_notices):
        resp = client.post(
            "/api/v1/leads/capture",
            json={"industry": "전기공사", "region": "부산광역시", "phone": "010-1234-5678"},
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
