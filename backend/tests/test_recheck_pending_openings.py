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


class TestWindowIsolation:
    """창 하나의 결함이 나머지 날짜를 죽이면 안 된다.

    표적 재조회는 **오래된 순 고정**이라, 한 날짜가 매번 실패하면 그 날짜가
    21일 동안 큐를 막고 뒤의 날짜는 한 번도 처리되지 않는다.
    """

    def _seed_pages(self, monkeypatch, engine, bad_date):
        from sqlalchemy.orm import sessionmaker

        monkeypatch.setattr(crawler, "SessionLocal", sessionmaker(bind=engine))
        monkeypatch.setattr(crawler, "_PAGE_INTERVAL_SEC", 0)
        seen = []

        def fake_fetch(start, end, page=1, num_rows=999):
            seen.append(start)
            if start.startswith(bad_date):
                raise RuntimeError("HTTP 502")
            return []

        monkeypatch.setattr(crawler, "_fetch_page", fake_fetch)
        return seen

    def test_one_bad_window_does_not_stop_the_rest(self, monkeypatch, engine):
        seen = self._seed_pages(monkeypatch, engine, bad_date="20260805")

        r = crawler.crawl_recent_openings(windows=crawler.windows_for_dates(
            [date(2026, 8, 5), date(2026, 8, 6), date(2026, 8, 7)]))

        assert r["ok"] is True                     # 부분 실패는 고장이 아니다
        assert len(r["failed_windows"]) == 1
        # 실패한 창 **뒤의** 날짜들이 실제로 조회됐다
        assert any(s.startswith("20260806") for s in seen)
        assert any(s.startswith("20260807") for s in seen)

    def test_all_windows_failing_is_reported_as_failure(self, monkeypatch, engine):
        self._seed_pages(monkeypatch, engine, bad_date="2026")

        r = crawler.crawl_recent_openings(windows=crawler.windows_for_dates(
            [date(2026, 8, 5), date(2026, 8, 6)]))

        assert r["ok"] is False                    # 전 창 실패는 고장이다
        assert len(r["failed_windows"]) == 2

    def test_participants_of_earlier_windows_survive_a_later_failure(
            self, monkeypatch, engine):
        """앞 창의 참가자는 뒤 창이 실패해도 저장돼 있어야 한다.

        참가자를 전 창 종료 후 한꺼번에 저장하면, 뒤 창의 예외가 앞 창에서 모은
        참가자를 통째로 지운다. 그런데 참여사수(`OpeningResult`)는 창 단위로 이미
        커밋돼 있어 **두 저장소가 영구히 갈라진다** — 정기 크롤과 달리 재조회에는
        자기 치유가 없다(그 날짜는 곧 대상에서 빠진다).
        """
        from sqlalchemy.orm import sessionmaker

        Session = sessionmaker(bind=engine)
        s = Session()
        s.add(models.MockBid(
            bid_no="WISO-1-000", arm="standard",
            registered_at=mb.now_kst() - timedelta(days=1),
            deadline_at=mb.now_kst() - timedelta(hours=2),
            price=97_500_000, snapshot_basic_price=100_000_000, status="REGISTERED"))
        s.commit()
        s.close()

        good = [{"bidNtceNo": "WISO-1", "bidNtceOrd": "000", "opengRank": "1",
                 "bidprcAmt": "90000000", "bidprcRt": "90.0", "bidprcCorpNm": "A건설",
                 "sucsfYn": "Y", "fnlSucsfAmt": "90000000", "fnlSucsfRt": "90.0",
                 "bssAmt": "100000000", "rsrvtnPrce": "100000000",
                 "opengDate": "2026-08-05"}]
        monkeypatch.setattr(crawler, "SessionLocal", Session)
        monkeypatch.setattr(crawler, "_PAGE_INTERVAL_SEC", 0)
        monkeypatch.setattr(
            crawler, "_fetch_page",
            lambda start, end, page=1, num_rows=999: (
                (_ for _ in ()).throw(RuntimeError("HTTP 502"))
                if start.startswith("20260806")
                else (good if page == 1 else [])))

        crawler.crawl_recent_openings(windows=crawler.windows_for_dates(
            [date(2026, 8, 5), date(2026, 8, 6)]))

        s = Session()
        try:
            assert s.query(models.OpeningParticipant).filter_by(
                bid_no="WISO-1-000").count() == 1
        finally:
            s.close()


class TestTimezoneAxis:
    """개찰 API 의 날짜 파라미터는 **KST 표기**다. 운영 컨테이너는 UTC 다."""

    def test_clamp_uses_kst_not_container_time(self, monkeypatch):
        """UTC 로 자르면 9시간 과거를 요청해 그날 개찰(10~11시)을 통째로 놓친다.

        대상 날짜는 `pending_opening_dates` 가 `now_kst()` 로 고르는데 클램프만
        컨테이너 시각을 쓰면 두 축이 갈라진다.
        """
        # 컨테이너(UTC) 01:00 = KST 10:00
        utc_now = datetime(2026, 8, 13, 1, 0)

        class _Frozen(datetime):
            @classmethod
            def now(cls, tz=None):
                return utc_now.replace(tzinfo=tz) + (tz.utcoffset(None) if tz else timedelta(0))

        monkeypatch.setattr(crawler, "datetime", _Frozen)
        (_, end), = crawler.windows_for_dates([date(2026, 8, 13)])

        assert end.hour == 10          # KST 10:00 — UTC 01:00 이 아니다


class TestFutureWindowClamp:
    def test_today_is_clamped_to_now(self, monkeypatch):
        """미래 종료시각을 요청하면 API 가 "입력범위값 초과 에러"를 낸다."""
        fixed = datetime(2026, 8, 13, 10, 0)

        class _Frozen(datetime):
            @classmethod
            def now(cls, tz=None):
                return fixed

        monkeypatch.setattr(crawler, "datetime", _Frozen)
        (start, end), = crawler.windows_for_dates([date(2026, 8, 13)])

        assert end == fixed          # 23:59 가 아니라 현재 시각

    def test_future_date_yields_no_window(self, monkeypatch):
        fixed = datetime(2026, 8, 13, 10, 0)

        class _Frozen(datetime):
            @classmethod
            def now(cls, tz=None):
                return fixed

        monkeypatch.setattr(crawler, "datetime", _Frozen)
        assert crawler.windows_for_dates([date(2026, 8, 20)]) == []


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
