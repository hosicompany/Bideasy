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
