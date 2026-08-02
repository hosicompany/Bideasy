from datetime import datetime
import time

import pytest

from app.db import models
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


# ── Phase 2 — 참가자 수집 (모의투찰 등록 공고 한정, 설계 §P4) ──


def _make_mock_bid(bid_no):
    from datetime import timedelta

    from app.services.mock_bidding import now_kst

    return models.MockBid(
        bid_no=bid_no, arm="standard",
        registered_at=now_kst() - timedelta(hours=1),
        deadline_at=now_kst() + timedelta(hours=1),
        price=97_500_000, snapshot_basic_price=100_000_000,
        status="REGISTERED",
    )


class TestParticipantParsing:
    def test_parses_participant_row(self):
        """낙찰자 판별(_parse_item_to_kwargs)이 버리는 참가자 행을 여기서 줍는다."""
        p = crawler._parse_participant_kwargs({
            "bidNtceNo": "P-1", "bidNtceOrd": "000",
            "opengRank": "2", "bidprcAmt": "91000000", "bidprcRt": "91.0",
            "bidprcCorpNm": "비낙찰건설", "sucsfYn": "N",
        })
        assert p["bid_no"] == "P-1-000"
        assert p["rank"] == 2
        assert p["bid_price"] == 91_000_000
        assert p["sucsf_yn"] == "N"

    def test_winner_row_is_also_a_participant(self):
        p = crawler._parse_participant_kwargs({
            "bidNtceNo": "P-2", "opengRank": "1", "bidprcAmt": "90000000",
            "bidprcCorpNm": "낙찰건설", "sucsfYn": "Y", "fnlSucsfAmt": "90000000",
        })
        assert p is not None and p["sucsf_yn"] == "Y"

    def test_skips_row_without_price(self):
        """투찰가 없는 행은 등수 재구성에 쓸 수 없다."""
        assert crawler._parse_participant_kwargs({"bidNtceNo": "P-3", "opengRank": "1"}) is None

    def test_missing_rank_is_tolerated(self):
        p = crawler._parse_participant_kwargs({"bidNtceNo": "P-4", "bidprcAmt": "80000000"})
        assert p is not None and p["rank"] is None


class TestParticipantSave:
    def test_resave_replaces_not_duplicates(self, db_session):
        """재크롤 시 공고 단위 삭제-재삽입 — (bid_no, rank) UNIQUE 대신 쓰는 방식.

        적격검사 진행 중 sucsfYn 이 N→Y 로 바뀌므로 갈아끼우는 편이 정확하다.
        """
        rows = [
            {"bid_no": "PSAVE-1-000", "rank": 1, "company": "A", "bid_price": 90_000_000,
             "bid_rate": 90.0, "sucsf_yn": "N"},
            {"bid_no": "PSAVE-1-000", "rank": 2, "company": "B", "bid_price": 91_000_000,
             "bid_rate": 91.0, "sucsf_yn": "N"},
        ]
        crawler._save_participants(db_session, {"PSAVE-1-000": rows})
        rows[0]["sucsf_yn"] = "Y"  # 적격검사 통과 반영된 재크롤
        r = crawler._save_participants(db_session, {"PSAVE-1-000": rows})

        saved = (db_session.query(models.OpeningParticipant)
                 .filter_by(bid_no="PSAVE-1-000").all())
        assert r["participant_rows"] == 2
        assert len(saved) == 2  # 중복 없이 교체
        assert {p.sucsf_yn for p in saved if p.rank == 1} == {"Y"}

    def test_bigint_price_fits(self, db_session):
        """공사 투찰가는 int4(21.4억)를 넘는다 — mock_bids 에서 실제로 겪은 사고."""
        from sqlalchemy import BigInteger

        assert isinstance(models.OpeningParticipant.__table__.c.bid_price.type, BigInteger)

        crawler._save_participants(db_session, {"PSAVE-2-000": [
            {"bid_no": "PSAVE-2-000", "rank": 1, "company": "대형건설",
             "bid_price": 620_348_000_000, "bid_rate": 89.7, "sucsf_yn": "Y"},
        ]})
        row = (db_session.query(models.OpeningParticipant)
               .filter_by(bid_no="PSAVE-2-000").first())
        assert row.bid_price > 2_147_483_647


def test_crawl_saves_participants_only_for_registered(monkeypatch, engine):
    """전수 저장 금지(§P4) — 등록된 공고의 참가자만 담고 나머지는 버린다."""
    from sqlalchemy.orm import sessionmaker

    Session = sessionmaker(bind=engine)
    s = Session()
    s.add(_make_mock_bid("PCRAWL-1-000"))
    s.commit()
    s.close()

    items = [
        # 등록된 공고 — 낙찰자 + 참가자 2행 모두 저장돼야 한다
        {"bidNtceNo": "PCRAWL-1", "bidNtceOrd": "000", "opengRank": "1",
         "bidprcAmt": "90000000", "bidprcRt": "90.0", "bidprcCorpNm": "A건설",
         "sucsfYn": "Y", "fnlSucsfAmt": "90000000", "fnlSucsfRt": "90.0",
         "presmptPrce": "100000000", "rsrvtnPrce": "100000000", "opengDate": "2026-07-10"},
        {"bidNtceNo": "PCRAWL-1", "bidNtceOrd": "000", "opengRank": "2",
         "bidprcAmt": "91000000", "bidprcCorpNm": "B건설", "sucsfYn": "N"},
        # 미등록 공고 — 참가자를 저장하면 안 된다 (전수 저장 함정)
        {"bidNtceNo": "PCRAWL-2", "bidNtceOrd": "000", "opengRank": "1",
         "bidprcAmt": "80000000", "bidprcCorpNm": "C건설", "sucsfYn": "Y",
         "fnlSucsfAmt": "80000000", "presmptPrce": "100000000"},
    ]
    monkeypatch.setattr(crawler, "SessionLocal", Session)
    monkeypatch.setattr(crawler, "_fetch_page",
                        lambda start, end, page=1, num_rows=999: items if page == 1 else [])

    result = crawler.crawl_recent_openings(days_back=0, max_pages=2)

    assert result["ok"] is True
    assert result["participant_bids"] == 1
    assert result["participant_rows"] == 2

    s = Session()
    try:
        assert s.query(models.OpeningParticipant).filter_by(bid_no="PCRAWL-1-000").count() == 2
        assert s.query(models.OpeningParticipant).filter_by(bid_no="PCRAWL-2-000").count() == 0
    finally:
        s.close()


def test_daily_crawl_task_fails_when_crawler_reports_failure(monkeypatch):
    monkeypatch.setattr(
        crawler,
        "crawl_recent_openings",
        lambda days_back=2: {"ok": False, "error": "public API failure"},
    )

    with pytest.raises(RuntimeError, match="public API failure"):
        verification_tasks.daily_crawl_opening_results(days_back=2)
