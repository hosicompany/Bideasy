"""Tests for AI analysis endpoint."""
import pytest

from app.core.rate_limit import limiter
from app.services.tips_generator import generate_tips


@pytest.fixture(autouse=True)
def _disable_rate_limiter():
    """Disable slowapi rate limiter during AI analysis tests.

    teardown 은 conftest 전역 기본값(False)으로 복구한다. True 로 두면 알파벳순
    뒤 테스트(register 등)가 리미터에 걸려 429 로 깨진다(2026-07-18 수정).
    """
    limiter.enabled = False
    yield
    limiter.enabled = False


class TestAiAnalysis:
    """GET /api/v1/ai/{bid_no}/analysis"""

    def test_analysis_requires_auth(self, client):
        """Unauthenticated request returns 401."""
        resp = client.get("/api/v1/ai/TEST-001/analysis")
        assert resp.status_code == 401

    def test_analysis_missing_data_returns_400(self, pro_client):
        """Analysis without title or basic_price returns 400."""
        resp = pro_client.get("/api/v1/ai/NONEXIST/analysis")
        assert resp.status_code == 400

    def test_analysis_with_query_params(self, pro_client, sample_notice, monkeypatch):
        """Analysis with query params succeeds."""
        monkeypatch.setattr(
            "app.services.scraper.ScraperService.fetch_page_content",
            lambda url: None,
        )
        resp = pro_client.get(
            "/api/v1/ai/TEST-001/analysis",
            params={
                "title": "서울시 강남구 구민회관 리모델링 공사",
                "basic_price": 500000000,
                "organization": "강남구청",
                "contract_type": "CONSTRUCTION",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "tips" in data or "summary" in data

    def test_legacy_basic_price_is_displayed_only_as_estimate(
        self, pro_client, sample_notice, monkeypatch
    ):
        monkeypatch.setattr(
            "app.services.scraper.ScraperService.fetch_page_content",
            lambda url: None,
        )
        resp = pro_client.get(
            "/api/v1/ai/TEST-001/analysis",
            params={"title": "가격 의미 테스트", "basic_price": 500_000_000},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert "추정가격" in data["summary"]
        assert data["price_info"]["basis_status"] == "unconfirmed"
        assert data["price_info"]["basic_price"] is None
        assert data["price_info"]["lower_limit"] is None
        assert "기초금액" in data["price_info"]["abstain_reason"]

    def test_qualification_not_leaked_via_cache(self, client, db_session, monkeypatch):
        """사용자별 자격이 캐시로 타인에게 노출되지 않음 (A FAIL → B PASS)."""
        monkeypatch.setattr("app.services.scraper.ScraperService.fetch_page_content", lambda url: None)
        from app.db import models
        from app.core.security import create_access_token
        db_session.add(models.Notice(bid_no="QUAL-RGN", title="부산 도로 공사",
                                     basic_price=100000000, region="부산광역시", contract_type="CONSTRUCTION"))
        a = models.User(email="qual-a@test.com", hashed_password="x", location="서울특별시", tier="pro")
        b = models.User(email="qual-b@test.com", hashed_password="x", location="부산광역시", tier="pro")
        db_session.add_all([a, b]); db_session.commit(); db_session.refresh(a); db_session.refresh(b)
        ta = create_access_token({"sub": str(a.id)})
        tb = create_access_token({"sub": str(b.id)})
        # A 먼저(캐시 생성) → B(캐시 히트). B 는 B 의 자격을 받아야 함.
        ra = client.get("/api/v1/ai/QUAL-RGN/analysis", headers={"Authorization": f"Bearer {ta}"})
        rb = client.get("/api/v1/ai/QUAL-RGN/analysis", headers={"Authorization": f"Bearer {tb}"})
        assert ra.status_code == 200 and rb.status_code == 200
        assert ra.json().get("qualification", {}).get("status") == "FAIL"   # 서울 업체 → 부산 한정 미달
        assert rb.json().get("qualification", {}).get("status") == "PASS"   # 부산 업체 → 충족 (누수 없음)

    def test_analysis_cache_hit(self, pro_client, sample_notice, monkeypatch):
        """Second call should return cached result."""
        monkeypatch.setattr(
            "app.services.scraper.ScraperService.fetch_page_content",
            lambda url: None,
        )
        params = {
            "title": "캐시 테스트 공사",
            "basic_price": 100000000,
            "contract_type": "CONSTRUCTION",
        }
        r1 = pro_client.get("/api/v1/ai/TEST-001/analysis", params=params)
        r2 = pro_client.get("/api/v1/ai/TEST-001/analysis", params=params)
        assert r1.status_code == 200
        assert r2.status_code == 200

    def test_price_context_correction_invalidates_cached_analysis(
        self, pro_client, db_session, monkeypatch
    ):
        from app.db import models

        monkeypatch.setattr(
            "app.services.scraper.ScraperService.fetch_page_content",
            lambda url: None,
        )
        notice = models.Notice(
            bid_no="AI-PRICE-REV-000",
            title="가격 정정 캐시 테스트",
            basic_price=90_000_000,
            contract_type="CONSTRUCTION",
        )
        db_session.add(notice)
        db_session.commit()

        before = pro_client.get("/api/v1/ai/AI-PRICE-REV-000/analysis")
        assert before.status_code == 200
        assert before.json()["price_info"]["basis_status"] == "unconfirmed"

        notice.basis_amount = 100_000_000
        notice.lower_limit_rate = 89.745
        notice.a_value_applicable = "N"
        db_session.commit()

        after = pro_client.get("/api/v1/ai/AI-PRICE-REV-000/analysis")
        assert after.status_code == 200
        assert after.json()["price_info"]["basis_status"] == "confirmed"
        assert after.json()["price_info"]["lower_limit"]["amount"] == 89_745_000

    def test_clear_cache(self, pro_client, admin_client, sample_notice, monkeypatch):
        """DELETE cache endpoint works (관리자 전용)."""
        monkeypatch.setattr(
            "app.services.scraper.ScraperService.fetch_page_content",
            lambda url: None,
        )
        # Generate cache first (Pro 사용자)
        pro_client.get(
            "/api/v1/ai/TEST-001/analysis",
            params={"title": "test", "basic_price": 100000000},
        )
        # 비관리자(Pro)는 캐시 삭제 거부
        assert pro_client.delete("/api/v1/ai/TEST-001/analysis/cache").status_code == 403
        # 관리자는 삭제 가능
        resp = admin_client.delete("/api/v1/ai/TEST-001/analysis/cache")
        assert resp.status_code == 200


def test_tips_require_public_range_and_known_a_value_context():
    result = generate_tips(
        {
            "title": "확정 공사",
            "estimated_price": 90_000_000,
            "basis_amount": 100_000_000,
            "basis_status": "confirmed",
            "contract_type": "CONSTRUCTION",
            "lower_limit_rate": 89.745,
            "prdprc_range_bgn": -2,
            "prdprc_range_end": 2,
            "a_value_applicable": "N",
        }
    )

    price = result["price_info"]
    assert price["basic_price"] == 100_000_000
    assert price["estimated_price"] == 90_000_000
    assert price["estimated_price_range"]["min"] == 98_000_000
    assert price["estimated_price_range"]["max"] == 102_000_000
    assert price["lower_limit"]["amount"] == 89_745_000
    assert price.get("abstain_reason") is None


def test_tips_abstain_when_a_value_applicability_is_unknown():
    result = generate_tips(
        {
            "title": "A값 미확인 공사",
            "basis_amount": 100_000_000,
            "basis_status": "confirmed",
            "contract_type": "CONSTRUCTION",
            "lower_limit_rate": 89.745,
        }
    )

    price = result["price_info"]
    assert price["lower_limit"] is None
    assert price["a_value_status"] == "unknown"
    assert "A값" in price["abstain_reason"]
