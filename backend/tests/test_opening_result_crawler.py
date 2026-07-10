from datetime import datetime
import time

import pytest

from app.services import opening_result_crawler as crawler
from app.tasks import verification_tasks


class _FakeDB:
    def __init__(self):
        self.committed = False
        self.commit_count = 0
        self.rolled_back = False
        self.closed = False

    def commit(self):
        self.committed = True
        self.commit_count += 1

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


class _FrozenDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        value = cls(2026, 7, 10, 14, 16)
        return value.replace(tzinfo=tz) if tz else value


def test_recent_crawl_splits_two_days_into_api_safe_calendar_windows(monkeypatch):
    calls = []
    db = _FakeDB()

    def fake_fetch(start_dt, end_dt, page=1, num_rows=100):
        calls.append((start_dt, end_dt, page))
        return []

    monkeypatch.setattr(crawler, "datetime", _FrozenDateTime)
    monkeypatch.setattr(crawler, "SessionLocal", lambda: db)
    monkeypatch.setattr(crawler, "_fetch_page", fake_fetch)

    result = crawler.crawl_recent_openings(days_back=2, max_pages=1)

    assert result["ok"] is True
    assert calls == [
        ("202607081416", "202607082359", 1),
        ("202607090000", "202607092359", 1),
        ("202607100000", "202607101416", 1),
    ]
    assert db.committed is True
    assert db.closed is True


def test_fetch_page_raises_when_public_api_returns_error(monkeypatch):
    class FakeResponse:
        status_code = 200

        @staticmethod
        def json():
            return {
                "nkoneps.com.response.ResponseError": {
                    "header": {"resultMsg": "입력범위값 초과 에러"}
                }
            }

    monkeypatch.setattr(crawler.requests, "get", lambda *args, **kwargs: FakeResponse())

    with pytest.raises(RuntimeError, match="입력범위값 초과 에러"):
        crawler._fetch_page("202607080000", "202607102359")


def test_fetch_page_verifies_tls_certificate(monkeypatch):
    request_kwargs = {}

    class FakeResponse:
        status_code = 200

        @staticmethod
        def json():
            return {"response": {"body": {"items": []}}}

    def fake_get(*args, **kwargs):
        request_kwargs.update(kwargs)
        return FakeResponse()

    monkeypatch.setattr(crawler.requests, "get", fake_get)

    crawler._fetch_page("202607090000", "202607092359")

    assert request_kwargs.get("verify", True) is True


def test_fetch_page_uses_largest_supported_page_size(monkeypatch):
    request_params = {}

    class FakeResponse:
        status_code = 200

        @staticmethod
        def json():
            return {"response": {"body": {"items": []}}}

    def fake_get(*args, **kwargs):
        request_params.update(kwargs["params"])
        return FakeResponse()

    monkeypatch.setattr(crawler.requests, "get", fake_get)

    crawler._fetch_page("202607090000", "202607092359")

    assert request_params["numOfRows"] == 999


def test_fetch_page_retries_transient_http_error(monkeypatch):
    calls = []

    class FakeResponse:
        def __init__(self, status_code, payload):
            self.status_code = status_code
            self._payload = payload

        def json(self):
            return self._payload

    responses = iter([
        FakeResponse(502, {}),
        FakeResponse(200, {"response": {"body": {"items": [{"ok": True}]}}}),
    ])

    def fake_get(*args, **kwargs):
        calls.append(kwargs)
        return next(responses)

    monkeypatch.setattr(crawler.requests, "get", fake_get)
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)

    items = crawler._fetch_page("202607090000", "202607092359")

    assert items == [{"ok": True}]
    assert len(calls) == 2


def test_crawl_commits_each_completed_day_before_later_failure(monkeypatch):
    db = _FakeDB()
    calls = []

    def fake_fetch(start_dt, end_dt, page=1, num_rows=999):
        calls.append((start_dt, end_dt))
        if start_dt == "202607100000":
            raise RuntimeError("HTTP 502")
        return []

    monkeypatch.setattr(crawler, "datetime", _FrozenDateTime)
    monkeypatch.setattr(crawler, "SessionLocal", lambda: db)
    monkeypatch.setattr(crawler, "_fetch_page", fake_fetch)

    result = crawler.crawl_recent_openings(days_back=2, max_pages=1)

    assert result["ok"] is False
    assert calls == [
        ("202607081416", "202607082359"),
        ("202607090000", "202607092359"),
        ("202607100000", "202607101416"),
    ]
    assert db.commit_count == 2
    assert db.rolled_back is True
    assert db.closed is True


def test_failure_counts_only_rows_from_committed_days(monkeypatch):
    db = _FakeDB()

    def fake_fetch(start_dt, end_dt, page=1, num_rows=999):
        if start_dt != "202607100000":
            return []
        if page == 1:
            return [{"bidNtceNo": f"ROLLBACK-{i}"} for i in range(999)]
        raise RuntimeError("HTTP 502")

    monkeypatch.setattr(crawler, "datetime", _FrozenDateTime)
    monkeypatch.setattr(crawler, "SessionLocal", lambda: db)
    monkeypatch.setattr(crawler, "_fetch_page", fake_fetch)
    monkeypatch.setattr(
        crawler,
        "_parse_item_to_kwargs",
        lambda item: {"bid_no": item["bidNtceNo"]},
    )
    monkeypatch.setattr(crawler, "_upsert_opening_result", lambda *args, **kwargs: True)

    result = crawler.crawl_recent_openings(days_back=2, max_pages=2)

    assert result["ok"] is False
    assert result["inserted"] == 0
    assert result["updated"] == 0
    assert result["skipped"] == 0
    assert db.commit_count == 2
    assert db.rolled_back is True


def test_crawl_fails_instead_of_committing_when_page_cap_is_full(monkeypatch):
    db = _FakeDB()
    full_page = [{"bidNtceNo": str(i)} for i in range(999)]

    monkeypatch.setattr(crawler, "datetime", _FrozenDateTime)
    monkeypatch.setattr(crawler, "SessionLocal", lambda: db)
    monkeypatch.setattr(crawler, "_fetch_page", lambda *args, **kwargs: full_page)
    monkeypatch.setattr(crawler, "_parse_item_to_kwargs", lambda item: {"bid_no": item["bidNtceNo"]})
    monkeypatch.setattr(crawler, "_upsert_opening_result", lambda *args, **kwargs: False)

    result = crawler.crawl_recent_openings(days_back=0, max_pages=2)

    assert result["ok"] is False
    assert "page limit" in result["error"]
    assert db.committed is False
    assert db.rolled_back is True
    assert db.closed is True


def test_daily_crawl_task_fails_when_crawler_reports_failure(monkeypatch):
    monkeypatch.setattr(
        crawler,
        "crawl_recent_openings",
        lambda days_back=2: {"ok": False, "error": "public API failure"},
    )

    with pytest.raises(RuntimeError, match="public API failure"):
        verification_tasks.daily_crawl_opening_results(days_back=2)
