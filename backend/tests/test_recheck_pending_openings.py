"""채점 대기 공고의 개찰일 표적 재조회.

**왜 필요한가** (2026-08-13 운영 실측):
- 개찰은 마감 당일에 난다 — 채점 성공분 786공고의 마감→개찰 지연이 전부 0.0일.
- 그러나 **낙찰자 확정(적격심사)은 며칠~수주** 걸리고, 크롤러는 낙찰자 행만
  `OpeningResult` 로 저장한다.
- 정기 크롤은 개찰일 기준 2일 창이라, 그 안에 확정 안 된 공고는 **영영** 결과가
  안 붙는다. 채점 도달률이 마감 후 8~9일이 지나도 33.8% 에서 멈췄다
  (NO_RESULT 1,747공고 중 개찰 결과 보유 **0건**).
- 개찰 API 는 날짜 창 조회만 지원한다(공고번호를 주면 "필수값 입력 에러", 날짜와
  같이 줘도 무시). 그래서 그 공고의 개찰일을 통째로 다시 훑는 수밖에 없다.
"""
from datetime import date, datetime, timedelta

from app.db import models
from app.services import mock_bidding as mb
from app.services import opening_result_crawler as crawler
from app.tasks import verification_tasks


def _notice(bid_no, *, opening_date):
    return models.Notice(
        bid_no=bid_no, title="테스트 공고", basic_price=100_000_000,
        contract_type="CONSTRUCTION", bid_method="적격심사제",
        notice_kind="등록공고", opening_date=opening_date,
        end_date=mb.now_kst() - timedelta(hours=2),
    )


def _mock_bid(bid_no):
    return models.MockBid(
        bid_no=bid_no, arm="standard",
        registered_at=mb.now_kst() - timedelta(days=1),
        deadline_at=mb.now_kst() - timedelta(hours=2),
        price=97_500_000, snapshot_basic_price=100_000_000, status="REGISTERED",
    )


def _opening(bid_no):
    return models.OpeningResult(
        bid_no=bid_no, basic_price=100_000_000, reserved_price=100_000_000,
        winner_price=90_000_000, open_date=mb.now_kst() - timedelta(hours=1),
    )


class TestWindowsForDates:
    def test_covers_the_whole_day(self):
        (start, end), = crawler.windows_for_dates([date(2026, 8, 5)])
        assert start == datetime(2026, 8, 5, 0, 0)
        assert end == datetime(2026, 8, 5, 23, 59)

    def test_one_window_per_date(self):
        w = crawler.windows_for_dates([date(2026, 8, 5), date(2026, 8, 7)])
        assert len(w) == 2


class TestPendingOpeningDates:
    def _seed(self, db, bid_no, *, days_ago, opened=False):
        d = (mb.now_kst() - timedelta(days=days_ago)).strftime("%Y-%m-%d 11:00:00")
        db.add(_notice(bid_no, opening_date=d))
        db.add(_mock_bid(bid_no))
        if opened:
            db.add(_opening(bid_no))
        db.commit()

    def _clean(self, db):
        db.query(models.OpeningResult).delete()
        db.query(models.MockBid).delete()
        db.query(models.Notice).delete()
        db.commit()

    def test_returns_dates_of_unscored_notices(self, db_session):
        self._clean(db_session)
        self._seed(db_session, "RC-PENDING-000", days_ago=5)

        dates = mb.pending_opening_dates(db_session)

        assert dates == [(mb.now_kst() - timedelta(days=5)).date()]

    def test_skips_notices_that_already_have_results(self, db_session):
        """결과가 붙은 공고는 다시 훑을 이유가 없다 — 대상에서 자동으로 빠진다."""
        self._clean(db_session)
        self._seed(db_session, "RC-DONE-000", days_ago=5, opened=True)

        assert mb.pending_opening_dates(db_session) == []

    def test_gives_up_on_too_old_openings(self, db_session):
        """유찰·취소처럼 낙찰자가 영영 확정 안 되는 건이 매일 자리를 차지하면 안 된다."""
        self._clean(db_session)
        self._seed(db_session, "RC-ANCIENT-000", days_ago=40)

        assert mb.pending_opening_dates(db_session, max_days=21) == []

    def test_ignores_future_openings(self, db_session):
        """아직 개찰 전이면 조회해도 결과가 없다."""
        self._clean(db_session)
        future = (mb.now_kst() + timedelta(days=2)).strftime("%Y-%m-%d 11:00:00")
        db_session.add(_notice("RC-FUTURE-000", opening_date=future))
        db_session.add(_mock_bid("RC-FUTURE-000"))
        db_session.commit()

        assert mb.pending_opening_dates(db_session) == []

    def test_oldest_first_and_capped(self, db_session):
        """하루가 ~84페이지라 회당 처리량을 묶는다. 오래된 것부터 처리한다."""
        self._clean(db_session)
        for i in (3, 5, 7):
            self._seed(db_session, f"RC-MANY-{i}-000", days_ago=i)

        dates = mb.pending_opening_dates(db_session, limit=2)

        assert dates == [(mb.now_kst() - timedelta(days=d)).date() for d in (7, 5)]

    def test_malformed_opening_date_does_not_break_the_batch(self, db_session):
        """값 하나가 깨졌다고 재조회 전체가 멈추면 안 된다."""
        self._clean(db_session)
        db_session.add(_notice("RC-BAD-000", opening_date="개찰일미정"))
        db_session.add(_mock_bid("RC-BAD-000"))
        db_session.commit()
        self._seed(db_session, "RC-GOOD-000", days_ago=4)

        assert mb.pending_opening_dates(db_session) == [
            (mb.now_kst() - timedelta(days=4)).date()]


class TestRecheckTask:
    def test_skips_crawl_when_nothing_pending(self, db_session, monkeypatch):
        """대상이 없으면 API 를 부르지 않는다 — 하루 84페이지짜리 조회다."""
        called = []
        monkeypatch.setattr(crawler, "crawl_recent_openings",
                            lambda **kw: called.append(kw) or {"ok": True})
        monkeypatch.setattr(mb, "pending_opening_dates", lambda *a, **k: [])

        r = verification_tasks.recheck_pending_openings()

        assert r["dates"] == 0
        assert called == []

    def test_crawls_only_the_pending_dates(self, monkeypatch):
        """정기 크롤(2일 창)이 아니라 **지정한 날짜 창만** 훑는다."""
        captured = {}

        def fake_crawl(**kw):
            captured.update(kw)
            return {"ok": True, "inserted": 3}

        monkeypatch.setattr(crawler, "crawl_recent_openings", fake_crawl)
        monkeypatch.setattr(mb, "pending_opening_dates",
                            lambda *a, **k: [date(2026, 8, 5), date(2026, 8, 6)])

        r = verification_tasks.recheck_pending_openings()

        assert r["recheck_dates"] == ["2026-08-05", "2026-08-06"]
        assert "days_back" not in captured          # 창을 직접 지정한다
        assert captured["windows"] == [
            (datetime(2026, 8, 5, 0, 0), datetime(2026, 8, 5, 23, 59)),
            (datetime(2026, 8, 6, 0, 0), datetime(2026, 8, 6, 23, 59)),
        ]


class TestCrawlWithExplicitWindows:
    def test_empty_windows_is_a_noop(self):
        r = crawler.crawl_recent_openings(windows=[])
        assert r["ok"] is True and r["pages_fetched"] == 0

    def test_fetches_only_given_windows(self, monkeypatch, engine):
        from sqlalchemy.orm import sessionmaker

        calls = []
        monkeypatch.setattr(crawler, "SessionLocal", sessionmaker(bind=engine))
        monkeypatch.setattr(crawler, "_fetch_page",
                            lambda s, e, page=1, num_rows=999: calls.append((s, e)) or [])

        crawler.crawl_recent_openings(
            windows=crawler.windows_for_dates([date(2026, 8, 5)]))

        assert calls == [("202608050000", "202608052359")]
