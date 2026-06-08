"""Tests for bid feed and favorites endpoints."""
from datetime import datetime, timedelta

import pytest


class TestFeed:
    """GET /api/v1/bids/feed"""

    def test_feed_empty_db_triggers_crawl(self, client, monkeypatch):
        """When DB is empty, feed should attempt API crawl and return list."""
        # Mock CrawlerService to avoid real API calls
        monkeypatch.setattr(
            "app.services.crawler.CrawlerService.fetch_notices",
            lambda **kwargs: [],
        )
        monkeypatch.setattr(
            "app.services.crawler.CrawlerService.save_notices",
            lambda db, notices: 0,
        )
        resp = client.get("/api/v1/bids/feed")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_feed_with_db_notices(self, client, sample_notice):
        """Feed returns notices from DB."""
        resp = client.get("/api/v1/bids/feed")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) >= 1
        assert any(n["bid_no"] == "TEST-001" for n in data)

    def test_feed_pagination(self, client, sample_notice):
        """Pagination params work correctly."""
        resp = client.get("/api/v1/bids/feed?page=1&limit=1")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) <= 1

    def test_feed_keyword_search(self, client, monkeypatch):
        """Keyword search delegates to CrawlerService."""
        monkeypatch.setattr(
            "app.services.crawler.CrawlerService.is_region_keyword",
            lambda kw: False,
        )
        monkeypatch.setattr(
            "app.services.crawler.CrawlerService.fetch_notices",
            lambda **kwargs: [],
        )
        monkeypatch.setattr(
            "app.services.crawler.CrawlerService.save_notices",
            lambda db, notices: 0,
        )
        resp = client.get("/api/v1/bids/feed?keyword=리모델링")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


def _api_item(no, price, openg):
    return {"bidNtceNo": no, "bidNtceOrd": "00", "bidNtceNm": f"테스트{no}",
            "presmptPrce": price, "opengDt": openg}


class TestCrawlerMultiCategory:
    """crawler.fetch_notices 공사/용역/물품 fan-out"""

    def test_fans_out_all_three_categories(self, monkeypatch):
        from app.services.crawler import CrawlerService
        calls = []

        def fake_request(url, params):
            calls.append(url)
            return [_api_item("X", 100, "2026-12-31 10:00:00")]

        monkeypatch.setattr(CrawlerService, "_request_items", staticmethod(fake_request))
        out = CrawlerService.fetch_notices()  # category=None → 3종
        assert len(calls) == 3
        assert {n["contract_type"] for n in out} == {"CONSTRUCTION", "SERVICE", "GOODS"}

    def test_single_category_only_queries_one(self, monkeypatch):
        from app.services.crawler import CrawlerService
        calls = []

        def fake_request(url, params):
            calls.append(url)
            return [_api_item("X", 100, "2026-12-31 10:00:00")]

        monkeypatch.setattr(CrawlerService, "_request_items", staticmethod(fake_request))
        out = CrawlerService.fetch_notices(category="service")
        assert len(calls) == 1 and "Servc" in calls[0]
        assert all(n["contract_type"] == "SERVICE" for n in out)

    def test_no_mock_pollution_on_filtered_search(self, monkeypatch):
        """실데이터 없고 검색필터 있으면 mock 반환 안 함 (빈 리스트)."""
        from app.services.crawler import CrawlerService
        monkeypatch.setattr(CrawlerService, "_request_items", staticmethod(lambda u, p: []))
        assert CrawlerService.fetch_notices(keyword="없는공고") == []
        # 필터 없는 기본 조회는 mock 허용
        assert len(CrawlerService.fetch_notices()) > 0


class TestFeedFilters:
    """GET /feed 필터·정렬 (category·price·sort)"""

    def test_category_param_passed_to_crawler(self, client, monkeypatch):
        captured = {}

        def fake_fetch(**kwargs):
            captured.update(kwargs)
            return []

        monkeypatch.setattr("app.services.crawler.CrawlerService.fetch_notices", fake_fetch)
        monkeypatch.setattr("app.services.crawler.CrawlerService.save_notices", lambda db, n: 0)
        resp = client.get("/api/v1/bids/feed?category=service")
        assert resp.status_code == 200
        assert captured.get("category") == "service"

    def test_price_filter_and_sort(self, client, monkeypatch):
        from app.services.crawler import CrawlerService
        items = [
            CrawlerService._map_item(_api_item("A", 100, "2026-12-10 10:00:00"), "CONSTRUCTION"),
            CrawlerService._map_item(_api_item("B", 500, "2026-12-05 10:00:00"), "SERVICE"),
            CrawlerService._map_item(_api_item("C", 50, "2026-12-20 10:00:00"), "GOODS"),
        ]
        monkeypatch.setattr("app.services.crawler.CrawlerService.fetch_notices", lambda **k: list(items))
        monkeypatch.setattr("app.services.crawler.CrawlerService.save_notices", lambda db, n: 0)
        monkeypatch.setattr("app.services.crawler.CrawlerService.is_region_keyword", lambda kw: False)
        resp = client.get("/api/v1/bids/feed?keyword=테스트&price_min=80&sort=price")
        assert resp.status_code == 200
        prices = [n["basic_price"] for n in resp.json()]
        assert prices == [500, 100]  # 50 필터아웃, 내림차순 정렬


class TestFavorites:
    """POST /{bid_no}/favorite and GET /favorites/list"""

    def test_toggle_favorite_add(self, client, sample_notice):
        """Toggle creates a favorite."""
        resp = client.post("/api/v1/bids/TEST-001/favorite")
        assert resp.status_code == 200
        assert resp.json()["status"] == "added"

    def test_toggle_favorite_remove(self, client, sample_notice):
        """Toggle twice results in removal."""
        # Ensure it's added first (may already exist from prior test)
        r1 = client.post("/api/v1/bids/TEST-001/favorite")
        if r1.json()["status"] == "removed":
            # Was already added, add again
            client.post("/api/v1/bids/TEST-001/favorite")
        # Now remove
        resp = client.post("/api/v1/bids/TEST-001/favorite")
        assert resp.status_code == 200
        assert resp.json()["status"] == "removed"

    def test_favorites_list(self, client, sample_notice):
        """Get favorites list returns favorited notices."""
        client.post("/api/v1/bids/TEST-001/favorite")
        resp = client.get("/api/v1/bids/favorites/list")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
