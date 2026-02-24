"""Tests for AI analysis endpoint."""
import pytest

from app.core.rate_limit import limiter


@pytest.fixture(autouse=True)
def _disable_rate_limiter():
    """Disable slowapi rate limiter during AI analysis tests."""
    limiter.enabled = False
    yield
    limiter.enabled = True


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

    def test_clear_cache(self, pro_client, sample_notice, monkeypatch):
        """DELETE cache endpoint works."""
        monkeypatch.setattr(
            "app.services.scraper.ScraperService.fetch_page_content",
            lambda url: None,
        )
        # Generate cache first
        pro_client.get(
            "/api/v1/ai/TEST-001/analysis",
            params={"title": "test", "basic_price": 100000000},
        )
        resp = pro_client.delete("/api/v1/ai/TEST-001/analysis/cache")
        assert resp.status_code == 200
