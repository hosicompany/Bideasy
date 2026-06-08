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


def _api_item_named(no, name, org, price, openg):
    return {"bidNtceNo": no, "bidNtceOrd": "00", "bidNtceNm": name,
            "ntceInsttNm": org, "presmptPrce": price, "opengDt": openg}


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

    def _seed(self, db_session, rows):
        """rows: list of dict(bid_no,title,org,price,days,ctype). 누적 DB 시딩."""
        from app.db import models
        from datetime import datetime, timedelta
        now = datetime.now()
        for r in rows:
            if not db_session.query(models.Notice).filter_by(bid_no=r["bid_no"]).first():
                db_session.add(models.Notice(
                    bid_no=r["bid_no"], title=r["title"], organization=r.get("org"),
                    region=r.get("region"), basic_price=r["price"],
                    contract_type=r.get("ctype", "CONSTRUCTION"),
                    start_date=now, end_date=now + timedelta(days=r["days"]),
                ))
        db_session.commit()

    def test_price_filter_and_sort(self, client, db_session, monkeypatch):
        # 누적 DB 검색 — API 미호출(빈 응답 mock), 시딩된 DB 를 필터 검색
        monkeypatch.setattr("app.services.crawler.CrawlerService.fetch_notices", lambda **k: [])
        monkeypatch.setattr("app.services.crawler.CrawlerService.is_region_keyword", lambda kw: False)
        self._seed(db_session, [
            {"bid_no": "PF-A", "title": "PF필터 공고 A", "price": 100, "days": 5},
            {"bid_no": "PF-B", "title": "PF필터 공고 B", "price": 500, "days": 3},
            {"bid_no": "PF-C", "title": "PF필터 공고 C", "price": 50, "days": 10},
        ])
        resp = client.get("/api/v1/bids/feed?keyword=PF필터&price_min=80&sort=price")
        assert resp.status_code == 200
        prices = [n["basic_price"] for n in resp.json() if n["bid_no"].startswith("PF-")]
        assert prices == [500, 100]  # 50 필터아웃, 내림차순 정렬

    def test_keyword_relevance_filter(self, client, db_session, monkeypatch):
        """누적 DB 를 키워드(제목·기관·지역)로 검색 — 무관 공고 제외."""
        monkeypatch.setattr("app.services.crawler.CrawlerService.fetch_notices", lambda **k: [])
        monkeypatch.setattr("app.services.crawler.CrawlerService.is_region_keyword", lambda kw: False)
        self._seed(db_session, [
            {"bid_no": "KR-A", "title": "강남구 도로포장 공사", "org": "서울 강남구", "price": 100, "days": 5},
            {"bid_no": "KR-B", "title": "봉화군 풀베기 사업", "org": "경북 봉화군산림조합", "price": 200, "days": 3, "ctype": "SERVICE"},
        ])
        resp = client.get("/api/v1/bids/feed?keyword=강남구")
        assert resp.status_code == 200
        titles = [n["title"] for n in resp.json()]
        assert any("강남구" in t for t in titles)
        assert not any("봉화군" in t for t in titles)  # 무관 공고 제외


class TestFavorites:
    """POST/GET /{bid_no}/favorite, GET /favorites/list — 유저스코프."""

    def test_favorite_requires_auth(self, client, sample_notice):
        assert client.post("/api/v1/bids/TEST-001/favorite").status_code == 401
        assert client.get("/api/v1/bids/favorites/list").status_code == 401

    def test_toggle_status_and_list(self, free_client, sample_notice):
        # 상태 초기화 (이전 테스트 잔여 제거)
        if free_client.get("/api/v1/bids/TEST-001/favorite").json()["favorited"]:
            free_client.post("/api/v1/bids/TEST-001/favorite")
        # add
        assert free_client.post("/api/v1/bids/TEST-001/favorite").json()["status"] == "added"
        assert free_client.get("/api/v1/bids/TEST-001/favorite").json()["favorited"] is True
        lst = free_client.get("/api/v1/bids/favorites/list").json()
        assert any(n["bid_no"] == "TEST-001" for n in lst)
        # remove
        assert free_client.post("/api/v1/bids/TEST-001/favorite").json()["status"] == "removed"
        assert free_client.get("/api/v1/bids/TEST-001/favorite").json()["favorited"] is False


class TestQualificationAndAValue:
    """GET /{bid_no}/qualification, PUT /{bid_no}/a_value"""

    def test_a_value_report(self, free_client, sample_notice, db_session):
        from app.db import models
        resp = free_client.put("/api/v1/bids/TEST-001/a_value", json={"a_value": 15000000})
        assert resp.status_code == 200
        assert resp.json()["updated"] is True
        db_session.expire_all()
        n = db_session.query(models.Notice).filter_by(bid_no="TEST-001").first()
        assert n.a_value == 15000000

    def test_a_value_requires_auth(self, client, sample_notice):
        assert client.put("/api/v1/bids/TEST-001/a_value", json={"a_value": 1}).status_code == 401

    def test_qualification_returns_status(self, free_client, sample_notice):
        resp = free_client.get("/api/v1/bids/TEST-001/qualification")
        assert resp.status_code == 200
        assert resp.json()["status"] in ("PASS", "FAIL", "UNKNOWN")
