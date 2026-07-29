"""Tests for 무료 자격 진단 리드 엔드포인트 (/api/v1/leads)."""
from datetime import datetime, timedelta

import pytest


@pytest.fixture(autouse=True)
def _isolate_lead_rate_limit(monkeypatch):
    """리드 테스트는 로컬 Redis 및 이전 테스트 실행의 IP 카운터를 공유하지 않는다."""
    import app.api.v1.endpoints.leads as leads_mod

    leads_mod._ip_call_log.clear()
    monkeypatch.setattr(leads_mod, "_get_redis", lambda: None)
    yield
    leads_mod._ip_call_log.clear()


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


class TestColdDbWarm:
    """콜드-DB(활성 공고 0건) 워밍 — 실방문자 '0건' 오인 방지."""

    def _warm_notice_dict(self):
        return {
            "bid_no": "WARM-E1",
            "title": "부산 워밍초등학교 전기공사",
            "basic_price": 100000000,
            "contract_type": "CONSTRUCTION",
            "organization": "테스트기관",
            "region": "부산광역시",
            "start_date": datetime.now(),
            "end_date": datetime.now() + timedelta(days=5),
        }

    def test_cold_db_warms_and_matches_in_production(self, client, db_session, monkeypatch):
        """운영 환경 + 콜드 DB → 1회 크롤 워밍 후 매칭이 채워진다."""
        import app.api.v1.endpoints.leads as leads_mod
        from app.services.crawler import CrawlerService

        _clear_notices(db_session)  # 콜드 상태로 만든다

        calls = {"n": 0}

        def _fake_fetch(**kwargs):
            calls["n"] += 1
            return [self._warm_notice_dict()]

        monkeypatch.setattr(leads_mod.settings, "APP_ENV", "production")
        monkeypatch.setattr(leads_mod, "_get_redis", lambda: None)      # 폴백 락 경로(결정적)
        monkeypatch.setattr(leads_mod, "_last_warm_crawl_ts", 0.0)      # 락 획득 가능하게 리셋
        monkeypatch.setattr(CrawlerService, "fetch_notices", staticmethod(_fake_fetch))

        resp = client.post(
            "/api/v1/leads/diagnose",
            json={"industry": "전기공사", "region": "부산광역시"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert calls["n"] == 1                        # 콜드라서 워밍 크롤 1회 발생
        assert data["matched_count"] == 1             # 워밍된 공고가 매칭됨
        assert data["preview"][0]["bid_no"] == "WARM-E1"

    def test_non_production_does_not_crawl(self, client, db_session, monkeypatch):
        """비운영(개발·테스트) 환경에서는 콜드여도 크롤하지 않는다(네트워크·mock 오염 방지)."""
        import app.api.v1.endpoints.leads as leads_mod
        from app.services.crawler import CrawlerService

        _clear_notices(db_session)

        calls = {"n": 0}

        def _fake_fetch(**kwargs):
            calls["n"] += 1
            return [self._warm_notice_dict()]

        monkeypatch.setattr(leads_mod.settings, "APP_ENV", "development")
        monkeypatch.setattr(CrawlerService, "fetch_notices", staticmethod(_fake_fetch))

        resp = client.post(
            "/api/v1/leads/diagnose",
            json={"industry": "전기공사", "region": "부산광역시"},
        )
        assert resp.status_code == 200
        assert calls["n"] == 0                         # 크롤 미발생
        assert resp.json()["matched_count"] == 0

    def test_warm_lock_blocks_second_crawl(self, client, db_session, monkeypatch):
        """워밍 락 TTL 내 재요청은 크롤을 반복하지 않는다(스탬피드/DoS 가드)."""
        import app.api.v1.endpoints.leads as leads_mod
        from app.services.crawler import CrawlerService

        calls = {"n": 0}

        def _fake_fetch(**kwargs):
            calls["n"] += 1
            return []  # 저장 없음 → DB 계속 콜드 유지(락만으로 반복 차단되는지 검증)

        monkeypatch.setattr(leads_mod.settings, "APP_ENV", "production")
        monkeypatch.setattr(leads_mod, "_get_redis", lambda: None)
        monkeypatch.setattr(leads_mod, "_last_warm_crawl_ts", 0.0)
        monkeypatch.setattr(CrawlerService, "fetch_notices", staticmethod(_fake_fetch))

        _clear_notices(db_session)
        body = {"industry": "전기공사", "region": "부산광역시"}
        client.post("/api/v1/leads/diagnose", json=body)
        client.post("/api/v1/leads/diagnose", json=body)
        assert calls["n"] == 1   # TTL 내 2번째 요청은 락에 막혀 크롤 안 함


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
