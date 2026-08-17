from datetime import datetime, timedelta, timezone
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

    # 창 하나가 실패해도 나머지는 처리한다(창 단위 격리) — 실패 사실은
    # `failed_windows` 로 보고한다. 한 날짜의 결함이 나머지를 죽이면,
    # 표적 재조회에서 같은 독약 날짜가 매일 큐를 막는다.
    assert result["ok"] is True
    assert result["failed_windows"] == ["202607100000: RuntimeError: HTTP 502"]
    assert calls == [
        ("202607081416", "202607082359"),
        ("202607090000", "202607092359"),
        ("202607100000", "202607101416"),
    ]
    assert db.commit_count == 2          # 완료된 두 날은 커밋됐다
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

    # 실패한 창의 행은 집계에 들어가지 않는다(롤백됐으므로)
    assert result["ok"] is True
    assert result["failed_windows"] and "202607100000" in result["failed_windows"][0]
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

    def test_rank_absence_is_split_by_cause(self):
        """세 경우를 갈라 센다 — 필드 부재 / 빈 값 / 파싱 실패.

        `opengRank` 가 비어 있다는 건 그 투찰이 무효라는 뜻이라 **평소에도 큰
        수**다(실측 47.6%). 스키마 변경을 여기 뭉쳐 넣으면 증가가 묻혀서, 등수
        지표가 통째로 죽어도 화면은 "참가자 데이터 대기"와 똑같아 아무도 모른다.
        `rank_field_missing` 이 그 사고를 가리키는 유일한 신호다.
        """
        stats: dict = {}
        # 필드 자체가 없다 — 스키마 변경 의심
        crawler._parse_participant_kwargs(
            {"bidNtceNo": "P-5", "bidprcAmt": "80000000"}, stats)
        # 값이 비었다 — 무효 투찰(정상)
        crawler._parse_participant_kwargs(
            {"bidNtceNo": "P-5", "bidprcAmt": "81000000", "opengRank": ""}, stats)
        # 값은 있는데 정수가 아니다 — 형식 변경 의심
        crawler._parse_participant_kwargs(
            {"bidNtceNo": "P-5", "bidprcAmt": "82000000", "opengRank": "3위"}, stats)

        assert stats["rank_field_missing"] == 1
        assert stats["rank_absent"] == 1
        assert stats["rank_unparsed"] == 1
        assert stats["rows"] == 3     # 분모 — 절대값만으로는 해석할 수 없다

    def test_rows_counts_only_saved_participants(self):
        """가격이 없어 버려지는 행은 분모에 넣지 않는다."""
        stats: dict = {}
        assert crawler._parse_participant_kwargs(
            {"bidNtceNo": "P-6", "opengRank": "1"}, stats) is None
        assert stats.get("rows", 0) == 0


class TestParticipantSave:
    def test_recrawl_updates_in_place_without_duplicating(self, db_session):
        """재크롤은 **병합**한다 — 중복도 안 만들고 삭제도 안 한다.

        삭제-재삽입의 원래 명분(적격검사 sucsfYn N→Y 반영)은 그대로 지켜진다.
        `rank`·`sucsf_yn` 은 키가 아니라 갱신 대상이기 때문이다.
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
        assert r["participant_rows_changed"] == 1        # 바뀐 1행만 썼다
        assert len(saved) == 2                   # 중복 없음
        assert {p.sucsf_yn for p in saved if p.rank == 1} == {"Y"}

    def _rows(self, bid_no, n, start_rank=1):
        return [
            {"bid_no": bid_no, "rank": start_rank + i, "company": f"업체{i}",
             "bid_price": 90_000_000 + i * 1_000_000, "bid_rate": 90.0 + i,
             "sucsf_yn": "N"}
            for i in range(n)
        ]

    def test_partial_response_cannot_shrink_stored_rows(self, db_session):
        """부분 응답이 와도 기존 행이 사라지지 않는다 — 축소가 **구조적으로 불가**.

        삭제-재삽입이던 시절엔 "행 수가 줄면 보류" 가드가 필요했는데, 그 가드는
        정기 스케줄에서 원리적으로 동작할 수 없었다(공고당 조회가 2회뿐이라
        관측 경과가 24h 한 값 → 어떤 시효도 "항상 채택" 아니면 "영구 보류").
        병합으로 바꾸면 가드 자체가 필요 없다.
        """
        bid_no = "PSHRINK-1-000"
        crawler._save_participants(db_session, {bid_no: self._rows(bid_no, 12)})

        r = crawler._save_participants(db_session, {bid_no: self._rows(bid_no, 5)})

        saved = (db_session.query(models.OpeningParticipant)
                 .filter_by(bid_no=bid_no).all())
        assert len(saved) == 12                  # 완전 집합이 그대로 남는다
        assert r["participant_bids"] == 1        # 보류가 아니라 정상 처리다
        assert r["participant_final_counts"][bid_no] == 12

    def test_late_arrivals_are_added(self, db_session):
        """뒤늦게 도착한 참가자는 그대로 추가된다."""
        bid_no = "PGROW-1-000"
        crawler._save_participants(db_session, {bid_no: self._rows(bid_no, 3)})

        r = crawler._save_participants(db_session, {bid_no: self._rows(bid_no, 9)})

        saved = (db_session.query(models.OpeningParticipant)
                 .filter_by(bid_no=bid_no).all())
        assert len(saved) == 9
        assert r["participant_rows_changed"] == 6        # 새로 들어온 6행만 썼다
        assert r["participant_final_counts"][bid_no] == 9

    def test_final_snapshot_removes_rows_from_older_partial_snapshots(self, db_session):
        """낙찰자 확정 후엔 이전 스냅샷의 유령 행을 제거한다.

        운영 회귀를 그대로 재현한다. 진행 중 응답에서 B가 사라지고
        C의 API 순위가 3→2로 바뀌었는데 병합만 하면 B(2위)와 C(2위)가
        다른 가격으로 함께 남아 가상 순위를 뒤로 밀어버린다.
        """
        bid_no = "PFINAL-1-000"
        first = self._rows(bid_no, 3)
        crawler._save_participants(db_session, {bid_no: first})

        current = [dict(first[0]), dict(first[2])]
        current[1]["rank"] = 2
        crawler._save_participants(db_session, {bid_no: current})

        mixed = (db_session.query(models.OpeningParticipant)
                 .filter_by(bid_no=bid_no).order_by(models.OpeningParticipant.bid_price)
                 .all())
        assert [(p.rank, p.bid_price) for p in mixed] == [
            (1, 90_000_000), (2, 91_000_000), (2, 92_000_000),
        ]

        current[0]["sucsf_yn"] = "Y"  # 낙찰자 확정 = 최종 스냅샷
        result = crawler._save_participants(db_session, {bid_no: current})

        saved = (db_session.query(models.OpeningParticipant)
                 .filter_by(bid_no=bid_no).order_by(models.OpeningParticipant.bid_price)
                 .all())
        assert [(p.rank, p.bid_price) for p in saved] == [
            (1, 90_000_000), (2, 92_000_000),
        ]
        assert result["participant_finalized_replacements"] == 1
        assert result["participant_axis_rejected"] == 0
        assert result["participant_final_counts"][bid_no] == 2

    def test_incoherent_final_snapshot_is_rejected_as_a_whole(self, db_session):
        """API 응답 자체의 순위가 틀리면 정상 스냅샷을 덮어쓰지 않는다."""
        bid_no = "PFINAL-BAD-1-000"
        good = self._rows(bid_no, 3)
        crawler._save_participants(db_session, {bid_no: good})

        bad = [dict(row) for row in good]
        bad[0]["rank"], bad[1]["rank"] = 2, 1
        bad[0]["sucsf_yn"] = "Y"
        result = crawler._save_participants(db_session, {bid_no: bad})

        saved = (db_session.query(models.OpeningParticipant)
                 .filter_by(bid_no=bid_no).order_by(models.OpeningParticipant.bid_price)
                 .all())
        assert [p.rank for p in saved] == [1, 2, 3]
        assert result["participant_finalized_replacements"] == 0
        assert result["participant_axis_rejected"] == 1
        assert result["participant_final_counts"][bid_no] == 3

    def test_rank_can_be_assigned_later(self, db_session):
        """무효로 들어온 참가자가 나중에 순위를 받으면 갱신된다(행이 늘지 않는다).

        `rank` 를 키에 넣었다면 같은 참가자가 두 행이 됐을 것이다.
        """
        bid_no = "PLATERANK-1-000"
        row = {"bid_no": bid_no, "rank": None, "company": "A건설",
               "bid_price": 90_000_000, "bid_rate": 90.0, "sucsf_yn": "N"}
        crawler._save_participants(db_session, {bid_no: [dict(row)]})

        row["rank"] = 3
        crawler._save_participants(db_session, {bid_no: [dict(row)]})

        saved = (db_session.query(models.OpeningParticipant)
                 .filter_by(bid_no=bid_no).all())
        assert len(saved) == 1
        assert saved[0].rank == 3

    def test_identical_rows_are_deduped_without_special_cases(self, db_session):
        """dedup 키에 분기를 두지 않는다.

        상호 결측(실측 0건/462,900행)을 위해 `if not company` 분기를 뒀더니,
        축소 가드와 합성돼 한 번 부풀려 저장된 공고가 영영 복구되지 않았다.
        이 코드에서 회귀는 늘 "특수 케이스를 분기로 빼는" 데서 났다.
        """
        bid_no = "PDEDUP-1-000"
        row = {"bid_no": bid_no, "rank": None, "company": "", "bid_price": 88_000_000,
               "bid_rate": 88.0, "sucsf_yn": "N"}
        crawler._save_participants(db_session, {bid_no: [dict(row), dict(row)]})

        # 완전히 같은 행은 하나로 — 상호 유무로 동작이 갈리지 않는다
        assert (db_session.query(models.OpeningParticipant)
                .filter_by(bid_no=bid_no).count()) == 1

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
    assert result["participant_rows_changed"] == 2

    s = Session()
    try:
        assert s.query(models.OpeningParticipant).filter_by(bid_no="PCRAWL-1-000").count() == 2
        assert s.query(models.OpeningParticipant).filter_by(bid_no="PCRAWL-2-000").count() == 0
    finally:
        s.close()


def test_crawl_reports_participant_scope_failure(monkeypatch, engine):
    """등록 목록 조회가 깨지면 그 회차 참가자 수집이 통째로 생략된다 — 그 사실을
    반드시 위로 올린다. 조용히 넘기면 크롤은 매일 초록불인데 등수 지표만 성장을
    멈추고, 화면은 "참가자 데이터 대기"와 구분되지 않는다(설계 §9 원칙).
    """
    from sqlalchemy.orm import sessionmaker

    Session = sessionmaker(bind=engine)
    monkeypatch.setattr(crawler, "SessionLocal", Session)
    monkeypatch.setattr(crawler, "_fetch_page", lambda *a, **k: [])
    monkeypatch.setattr(crawler, "_load_registered_bid_nos", lambda db: (set(), False))

    result = crawler.crawl_recent_openings(days_back=0, max_pages=2)

    assert result["ok"] is True             # 낙찰 결과 적재는 되돌리지 않는다
    assert result["participant_ok"] is False
    assert result["participant_scope_ok"] is False


def test_crawl_reports_structural_save_failure(monkeypatch, engine):
    """구조적 예외(테이블·컬럼 부재)는 **1건만 나와도** 고장이다.

    건수로 판정하면 두 방향으로 틀린다 — 대상이 1건인 날 데이터 결함 하나로
    배치가 red 가 되고, 반대로 처리하지 못한 건이 분모에 섞이면 진짜 고장이
    초록불이 된다.
    """
    from sqlalchemy.orm import sessionmaker

    Session = sessionmaker(bind=engine)
    s = Session()
    s.add(_make_mock_bid("PFAIL-1-000"))
    s.commit()
    s.close()

    items = [{"bidNtceNo": "PFAIL-1", "bidNtceOrd": "000", "opengRank": "1",
              "bidprcAmt": "90000000", "bidprcCorpNm": "A건설", "sucsfYn": "Y",
              "fnlSucsfAmt": "90000000", "presmptPrce": "100000000"}]
    monkeypatch.setattr(crawler, "SessionLocal", Session)
    monkeypatch.setattr(crawler, "_fetch_page",
                        lambda start, end, page=1, num_rows=999: items if page == 1 else [])
    monkeypatch.setattr(crawler, "_save_participants",
                        lambda db, by_bid: {"participant_bids": 0, "participant_rows_changed": 0,
                                            "participant_errors": 1,
                                            "participant_structural_errors": 1,
                                            "participant_final_counts": {}})

    result = crawler.crawl_recent_openings(days_back=0, max_pages=2)

    assert result["ok"] is True                    # 낙찰 결과 적재는 되돌리지 않는다
    assert result["participant_targets"] == 1
    assert result["participant_ok"] is False


def test_participant_count_uses_same_key_as_storage(monkeypatch, engine):
    """참여사수와 저장 행 수가 같은 정의를 쓴다.

    raw 행을 그냥 더하면 API 가 같은 행을 두 번 준 날 `participants_count` 만
    부풀어 `opening_participants` 행 수와 영구히 어긋난다. 그 값은 공개 SSR
    공고 상세·누적 통계·블로그 자동 초안으로 나간다.
    """
    from sqlalchemy.orm import sessionmaker

    Session = sessionmaker(bind=engine)
    s = Session()
    s.add(_make_mock_bid("PDUPCNT-1-000"))
    s.commit()
    s.close()

    row = {"bidNtceNo": "PDUPCNT-1", "bidNtceOrd": "000", "opengRank": "1",
           "bidprcAmt": "90000000", "bidprcRt": "90.0", "bidprcCorpNm": "A건설",
           "sucsfYn": "Y", "fnlSucsfAmt": "90000000", "fnlSucsfRt": "90.0",
           "presmptPrce": "100000000", "rsrvtnPrce": "100000000",
           "bssAmt": "100000000", "opengDate": "2026-07-10"}
    items = [dict(row), dict(row)]        # API 가 같은 행을 두 번 줬다
    monkeypatch.setattr(crawler, "SessionLocal", Session)
    monkeypatch.setattr(crawler, "_fetch_page",
                        lambda start, end, page=1, num_rows=999: items if page == 1 else [])

    crawler.crawl_recent_openings(days_back=0, max_pages=2)

    s = Session()
    try:
        saved = s.query(models.OpeningParticipant).filter_by(
            bid_no="PDUPCNT-1-000").count()
        opening = s.query(models.OpeningResult).filter_by(
            bid_no="PDUPCNT-1-000").first()
        assert saved == 1
        assert opening.participants_count == saved   # 두 저장소가 같은 말을 한다
    finally:
        s.close()


def test_data_error_alone_is_not_a_structural_failure(monkeypatch, engine):
    """대상이 1건뿐인 날 그 1건이 데이터 결함으로 실패해도 배치는 red 가 아니다.

    건수 기준(`errors >= targets`)이면 `1 >= 1` 로 매번 걸린다. 모의투찰 등록분
    중 하루 개찰 도래는 한 자릿수가 흔하므로 자주 발생한다.
    """
    from sqlalchemy.orm import sessionmaker

    Session = sessionmaker(bind=engine)
    s = Session()
    s.add(_make_mock_bid("PDATAERR-1-000"))
    s.commit()
    s.close()

    items = [{"bidNtceNo": "PDATAERR-1", "bidNtceOrd": "000", "opengRank": "1",
              "bidprcAmt": "90000000", "bidprcCorpNm": "A건설", "sucsfYn": "Y",
              "fnlSucsfAmt": "90000000", "presmptPrce": "100000000"}]
    monkeypatch.setattr(crawler, "SessionLocal", Session)
    monkeypatch.setattr(crawler, "_fetch_page",
                        lambda start, end, page=1, num_rows=999: items if page == 1 else [])
    monkeypatch.setattr(crawler, "_save_participants",
                        lambda db, by_bid: {"participant_bids": 0, "participant_rows_changed": 0,
                                            "participant_errors": 1,
                                            "participant_structural_errors": 0,
                                            "participant_final_counts": {}})

    result = crawler.crawl_recent_openings(days_back=0, max_pages=2)

    assert result["participant_errors"] == 1
    assert result["participant_ok"] is True     # 데이터 결함은 그 건만의 문제다


def test_structural_failure_is_caught_even_when_mixed_with_holds(monkeypatch, engine):
    """부분 실패가 섞여도 구조적 고장은 잡힌다.

    건수 비율로 판정하면 정상 상황의 꼬리가 고장이 되거나, 반대로 진짜 고장이
    분모에 묻힌다. 판정은 예외 **종류**로 한다.
    """
    from sqlalchemy.orm import sessionmaker

    Session = sessionmaker(bind=engine)
    s = Session()
    s.add(_make_mock_bid("PMIX-1-000"))
    s.commit()
    s.close()

    items = [{"bidNtceNo": "PMIX-1", "bidNtceOrd": "000", "opengRank": "1",
              "bidprcAmt": "90000000", "bidprcCorpNm": "A건설", "sucsfYn": "Y",
              "fnlSucsfAmt": "90000000", "presmptPrce": "100000000"}]
    monkeypatch.setattr(crawler, "SessionLocal", Session)
    monkeypatch.setattr(crawler, "_fetch_page",
                        lambda start, end, page=1, num_rows=999: items if page == 1 else [])
    # 20공고 중 6건 보류, 14건 시도 → 전부 구조적 실패
    monkeypatch.setattr(crawler, "_save_participants",
                        lambda db, by_bid: {"participant_bids": 0, "participant_rows_changed": 0,
                                            "participant_errors": 14,
                                            "participant_structural_errors": 14,
                                            "participant_final_counts": {}})

    result = crawler.crawl_recent_openings(days_back=0, max_pages=2)

    assert result["participant_ok"] is False


def test_participant_parse_wipeout_is_caught(monkeypatch, engine):
    """API 가 행을 줬는데 참가자가 0건이면 고장이다(가격 필드명 변경).

    `bidprcAmt` 는 낙찰자 판별에도 쓰이므로 이 사고에서는 본 크롤도 함께 죽는다.
    그래서 판정에 `inserted or updated` 를 걸면 정작 이 사고에서 침묵한다.
    """
    from sqlalchemy.orm import sessionmaker

    Session = sessionmaker(bind=engine)
    items = [{"bidNtceNo": "PWIPE-1", "bidNtceOrd": "000", "opengRank": "1",
              "bidPrcAmt": "90000000",          # ← 필드명이 바뀌었다
              "bidprcCorpNm": "A건설", "sucsfYn": "Y",
              "fnlSucsfAmt": "90000000", "presmptPrce": "100000000",
              "opengDate": "2026-07-10"}]
    monkeypatch.setattr(crawler, "SessionLocal", Session)
    monkeypatch.setattr(crawler, "_fetch_page",
                        lambda start, end, page=1, num_rows=999: items if page == 1 else [])

    result = crawler.crawl_recent_openings(days_back=0, max_pages=2)

    assert result["api_items"] > 0                      # API 는 행을 줬는데
    assert result["participant_parsed_rows"] == 0       # 참가자가 0건이다
    assert result["participant_ok"] is False


def test_rank_field_wipeout_is_caught(monkeypatch, engine):
    """순위 필드가 전멸하면 등수 지표가 죽는다 — 무효로 둔갑해 안 보인다."""
    from sqlalchemy.orm import sessionmaker

    Session = sessionmaker(bind=engine)
    s = Session()
    s.add(_make_mock_bid("PRANKGONE-1-000"))
    s.commit()
    s.close()

    items = [{"bidNtceNo": "PRANKGONE-1", "bidNtceOrd": "000",
              "opengRnkNo": "1",                # ← opengRank 가 사라졌다
              "bidprcAmt": "90000000", "bidprcCorpNm": "A건설", "sucsfYn": "Y",
              "fnlSucsfAmt": "90000000", "presmptPrce": "100000000"}]
    monkeypatch.setattr(crawler, "SessionLocal", Session)
    monkeypatch.setattr(crawler, "_fetch_page",
                        lambda start, end, page=1, num_rows=999: items if page == 1 else [])

    result = crawler.crawl_recent_openings(days_back=0, max_pages=2)

    assert result["rank_field_missing"] == result["participant_parsed_rows"] > 0
    assert result["participant_ok"] is False


def test_daily_crawl_task_fails_when_participants_collapse(monkeypatch):
    """부분 실패는 넘어가고, 전면 실패만 태스크를 FAILURE 로 만든다.

    데이터 결함 1건으로 매일 배치를 red 로 만들면 경보가 무뎌진다.
    """
    monkeypatch.setattr(
        crawler, "crawl_recent_openings",
        lambda days_back=2: {"ok": True, "participant_ok": False, "participant_targets": 12},
    )
    with pytest.raises(RuntimeError, match="participant collection failed"):
        verification_tasks.daily_crawl_opening_results(days_back=2)

    monkeypatch.setattr(
        crawler, "crawl_recent_openings",
        lambda days_back=2: {"ok": True, "participant_ok": True,
                             "participant_errors": 1, "participant_bids": 11},
    )
    assert verification_tasks.daily_crawl_opening_results(days_back=2)["participant_errors"] == 1


def test_daily_crawl_task_fails_when_crawler_reports_failure(monkeypatch):
    monkeypatch.setattr(
        crawler,
        "crawl_recent_openings",
        lambda days_back=2: {"ok": False, "error": "public API failure"},
    )

    with pytest.raises(RuntimeError, match="public API failure"):
        verification_tasks.daily_crawl_opening_results(days_back=2)


# ─────────────────────────────────────────────────────────────
# 금액 기준 회귀 가드 (2026-08-03)
#
# `presmptPrce` 는 추정가격(부가세 제외)이고 기초금액은 `bssAmt` 다.
# 예전 매핑 탓에 정적 개찰 파일과 기준이 섞여 백테스트 무효율이 99% 로
# 튀었다. 경위: docs/PRICE_BASE_DEFECT.md
# ─────────────────────────────────────────────────────────────

def _opening_item(**over):
    item = {
        "bidNtceNo": "R26BK99999999",
        "bidNtceOrd": "000",
        "bssAmt": "60929200",        # 기초금액
        "presmptPrce": "55390182",   # 추정가격 (= 기초금액 / 1.1)
        "rsrvtnPrce": "60990925",    # 예정가격
        "sucsfLwstlmtRt": "89.745",
        "fnlSucsfAmt": "55037188",
        "fnlSucsfRt": "90.238",
        "fnlSucsfCorpNm": "다건기업",
        "bidwinrDcsnMthdNm": "소액수의견적",
        "ntceInsttNm": "부경대학교",
        "opengDate": "2026-07-31",
        "opengTm": "13:00",
    }
    item.update(over)
    return item


class TestBasisAmountMapping:
    def test_basic_price_is_bss_amt_not_presmpt(self):
        kw = crawler._parse_item_to_kwargs(_opening_item())
        assert kw["basic_price"] == 60929200.0
        assert kw["basic_price"] != 55390182.0, "추정가격으로 회귀했다"

    def test_ratio_lands_in_plausible_band(self):
        """정정 후 사정률은 기초금액 ±3% 안이어야 한다 — 이게 판정의 전제다."""
        kw = crawler._parse_item_to_kwargs(_opening_item())
        ratio = kw["reserved_price"] / kw["basic_price"]
        assert 0.94 <= ratio <= 1.06, f"사정률 {ratio}"

    def test_lower_limit_rate_is_stored(self):
        kw = crawler._parse_item_to_kwargs(_opening_item())
        assert kw["lower_limit_rate"] == 89.745

    def test_missing_lower_limit_rate_is_none_not_zero(self):
        """0 으로 저장하면 '하한율 0%' 라는 거짓이 된다 — None 이라야 폴백이 돈다."""
        kw = crawler._parse_item_to_kwargs(_opening_item(sucsfLwstlmtRt=""))
        assert kw["lower_limit_rate"] is None

    def test_row_without_bss_amt_is_skipped(self):
        """기초금액이 없으면 추정가격으로 대체하지 않고 버린다 — 기준 혼입 방지."""
        assert crawler._parse_item_to_kwargs(_opening_item(bssAmt="")) is None

    def test_winner_rate_fallback_uses_reserved_price(self):
        """API 가 낙찰률을 안 줄 때도 기준은 예정가격 — 정적 파일과 같아야 한다."""
        kw = crawler._parse_item_to_kwargs(_opening_item(fnlSucsfRt="", bidprcRt=""))
        expected = round(55037188 / 60990925 * 100, 4)
        assert kw["winner_rate"] == expected


def test_db_records_prefer_stored_lower_limit_rate(db_session):
    """공고가 명시한 하한율이 있으면 금액대 테이블보다 그것을 쓴다."""
    from app.services.autocalibrate.dataset import load_records

    db_session.add(models.OpeningResult(
        bid_no="LLRSTORE-1", organization="A기관", bid_method="적격심사제",
        open_date=datetime(2026, 6, 1),
        basic_price=5e8,                 # 테이블상으로는 89.745%
        lower_limit_rate=86.745,         # 공고는 86.745% 라고 말한다
        reserved_price=5.02e8, winner_price=4.5e8, winner_rate=90.0,
    ))
    # commit 이 아니라 flush — db_session 픽스처는 rollback 만 하므로 커밋한 행은
    # 뒤 테스트로 새고, 건수를 세는 테스트를 깨뜨린다. flush 면 같은 세션의
    # 쿼리에는 보이면서 teardown 에서 사라진다.
    db_session.flush()

    rec = next(r for r in load_records(db=db_session) if r.bid_no == "LLRSTORE-1")
    assert rec.lower_limit_rate == 86.745


class TestParticipantCount:
    """참여사수 — API 가 참가자당 행 하나를 주므로 '행 수'가 곧 참여사수다.

    추가 API 호출 0. 그런데 2026-08-07 실측에서 `participants_count` 보유율이
    **0%** 였다 — 파서가 `None` 을 박아 놓고 아무도 안 채웠기 때문이다.
    """

    def test_apply_fills_count_even_when_winner_price_exists(self, db_session):
        """낙찰가가 이미 있는 행도 채워져야 한다.

        `_upsert_opening_result` 는 낙찰가가 있으면 갱신을 건너뛴다(실 결과는
        안 바뀐다는 규칙). 그 경로에 얹으면 기존 행은 영영 0 으로 남는다.
        """
        db_session.add(models.OpeningResult(
            bid_no="PC-1", organization="A기관", bid_method="적격심사제",
            open_date=datetime(2026, 7, 1),
            basic_price=1e8, reserved_price=1.01e8,
            winner_price=9e7, winner_rate=90.0,
        ))
        db_session.flush()

        updated = crawler._apply_participant_counts(db_session, {"PC-1": 37})

        assert updated == 1
        row = db_session.query(models.OpeningResult).filter_by(bid_no="PC-1").one()
        assert row.participants_count == 37

    def test_apply_ignores_unknown_bid_and_zero(self, db_session):
        """모르는 공고·0건은 건드리지 않는다 — 없는 행을 만들어 내지 않는다."""
        assert crawler._apply_participant_counts(db_session, {"NOPE-1": 5}) == 0
        assert crawler._apply_participant_counts(db_session, {}) == 0

    def test_apply_is_idempotent(self, db_session):
        """같은 값 재적용은 변경으로 세지 않는다(재크롤 시 잡음 방지)."""
        db_session.add(models.OpeningResult(
            bid_no="PC-2", basic_price=1e8, reserved_price=1.01e8,
            winner_price=9e7, participants_count=12,
        ))
        db_session.flush()

        assert crawler._apply_participant_counts(db_session, {"PC-2": 12}) == 0
        assert crawler._apply_participant_counts(db_session, {"PC-2": 13}) == 1

    def test_parse_participant_accepts_row_without_rank(self):
        """순위가 없어도 참가자 한 명이다 — 세는 데는 투찰가만 있으면 된다."""
        p = crawler._parse_participant_kwargs(
            _opening_item(bidprcAmt="55000000", opengRank=""))
        assert p is not None
        assert p["rank"] is None

    def test_parse_participant_rejects_row_without_price(self):
        assert crawler._parse_participant_kwargs(_opening_item()) is None


# ── 고장 신호가 사라지지 않는가 (리뷰가 프로브로만 재현했던 경로) ──


class _CommitFailDB(_FakeDB):
    """창 커밋만 실패하는 세션 — 참여사수 갱신이 롤백되는 상황."""

    def commit(self):
        self.commit_count += 1
        raise RuntimeError("disk full")


def test_counted_is_not_inflated_when_window_commit_fails(monkeypatch):
    """커밋이 터지면 롤백된 갱신이 숫자로 남으면 안 된다.

    창 하나만 실패하면 `ok:True` 라, "성공했고 5,000건 반영"으로 보고된다.
    같은 함수가 참가자 경로에서 지키는 규칙을 창 경로에서도 지켜야 한다.
    """
    db = _CommitFailDB()
    monkeypatch.setattr(crawler, "datetime", _FrozenDateTime)
    monkeypatch.setattr(crawler, "SessionLocal", lambda: db)
    monkeypatch.setattr(crawler, "_PAGE_INTERVAL_SEC", 0)
    monkeypatch.setattr(crawler, "_fetch_page", lambda *a, **k: [])
    monkeypatch.setattr(crawler, "_load_registered_bid_nos", lambda db: (set(), True))
    monkeypatch.setattr(crawler, "_apply_participant_counts", lambda db, counts: 5000)

    result = crawler.crawl_recent_openings(days_back=0, max_pages=2)

    assert result["participants_counted"] == 0     # 롤백됐으므로 0이어야 한다
    assert result["failed_windows"]


def test_structural_errors_survive_a_later_commit_failure(monkeypatch, engine):
    """저장이 구조적으로 실패한 사실이 뒤이은 예외에 묻히면 안 된다.

    `_save_participants` 가 센 `structural_errors` 를 커밋 **뒤에** 병합하면,
    그 사이가 터졌을 때 카운터가 통째로 버려진다. 연결이 끊겨 전부 실패했는데
    `participant_ok=True` 로 초록불이 된다 — 이 검출기가 존재하는 이유가
    정확히 그 상황이다.
    """
    from sqlalchemy.orm import sessionmaker

    Session = sessionmaker(bind=engine)
    s = Session()
    s.add(_make_mock_bid("SIG-1-000"))
    s.commit()
    s.close()

    items = [{"bidNtceNo": "SIG-1", "bidNtceOrd": "000", "opengRank": "1",
              "bidprcAmt": "90000000", "bidprcCorpNm": "A건설", "sucsfYn": "Y",
              "fnlSucsfAmt": "90000000", "bssAmt": "100000000",
              "rsrvtnPrce": "100000000", "opengDate": "2026-07-10"}]
    monkeypatch.setattr(crawler, "SessionLocal", Session)
    monkeypatch.setattr(crawler, "_PAGE_INTERVAL_SEC", 0)
    monkeypatch.setattr(crawler, "_fetch_page",
                        lambda s_, e_, page=1, num_rows=999: items if page == 1 else [])
    # 저장은 구조적으로 실패했다고 보고하고, 이어지는 참여사수 반영이 터진다
    monkeypatch.setattr(crawler, "_save_participants",
                        lambda db, by_bid: {"participant_bids": 0,
                                            "participant_rows_changed": 0,
                                            "participant_errors": 1,
                                            "participant_structural_errors": 1,
                                            "participant_final_counts": {"SIG-1-000": 1}})

    calls = {"n": 0}
    real_apply = crawler._apply_participant_counts

    def flaky_apply(db, counts):
        calls["n"] += 1
        if calls["n"] >= 2:          # 창 경로는 통과, 참가자 경로에서 터진다
            raise RuntimeError("connection lost")
        return real_apply(db, counts)

    monkeypatch.setattr(crawler, "_apply_participant_counts", flaky_apply)

    result = crawler.crawl_recent_openings(days_back=0, max_pages=2)

    assert result["participant_structural_errors"] >= 1
    assert result["participant_ok"] is False       # 초록불이 되면 안 된다


def test_count_apply_failure_is_itself_structural(monkeypatch, engine):
    """참여사수 반영은 순수 DB 작업이라, 거기서 터졌다는 건 구조적 문제다."""
    from sqlalchemy.orm import sessionmaker

    Session = sessionmaker(bind=engine)
    s = Session()
    s.add(_make_mock_bid("SIG-2-000"))
    s.commit()
    s.close()

    items = [{"bidNtceNo": "SIG-2", "bidNtceOrd": "000", "opengRank": "1",
              "bidprcAmt": "90000000", "bidprcCorpNm": "A건설", "sucsfYn": "Y",
              "fnlSucsfAmt": "90000000", "bssAmt": "100000000",
              "rsrvtnPrce": "100000000", "opengDate": "2026-07-10"}]
    monkeypatch.setattr(crawler, "SessionLocal", Session)
    monkeypatch.setattr(crawler, "_PAGE_INTERVAL_SEC", 0)
    monkeypatch.setattr(crawler, "_fetch_page",
                        lambda s_, e_, page=1, num_rows=999: items if page == 1 else [])
    # 저장 자체는 성공했는데(구조적 에러 0) 참여사수 반영만 터진다
    monkeypatch.setattr(crawler, "_save_participants",
                        lambda db, by_bid: {"participant_bids": 1,
                                            "participant_rows_changed": 1,
                                            "participant_errors": 0,
                                            "participant_structural_errors": 0,
                                            "participant_final_counts": {"SIG-2-000": 1}})

    calls = {"n": 0}
    real_apply = crawler._apply_participant_counts

    def flaky_apply(db, counts):
        calls["n"] += 1
        if calls["n"] >= 2:
            raise RuntimeError("connection lost")
        return real_apply(db, counts)

    monkeypatch.setattr(crawler, "_apply_participant_counts", flaky_apply)

    result = crawler.crawl_recent_openings(days_back=0, max_pages=2)

    assert result["participant_structural_errors"] == 1
    assert result["participant_ok"] is False


class _KstAwareFrozen(datetime):
    """축 변환을 **실제로 하는** 프리즈 — UTC/KST 차이를 재현한다.

    기존 `_FrozenDateTime` 은 `value.replace(tzinfo=tz)` 라 축을 바꾸지 않아,
    "컨테이너 시각을 그대로 보내면 9시간 어긋난다"는 결함을 재현하지 못한다.
    """

    _UTC_NOW = datetime(2026, 7, 10, 10, 0)      # = KST 19:00

    @classmethod
    def now(cls, tz=None):
        if tz is None:
            return cls._UTC_NOW                   # 컨테이너 시각(UTC)
        return cls._UTC_NOW.replace(tzinfo=timezone.utc).astimezone(tz)


def test_daily_crawl_window_uses_kst_not_container_time(monkeypatch):
    """19:00 KST 크롤이 "10:00 까지"를 요청하면 그날 개찰(10~11시)이 밀린다.

    개찰 API 의 `opengBgnDt/opengEndDt` 는 KST 표기인데 운영 컨테이너 TZ 는 UTC 다.
    """
    calls = []
    db = _FakeDB()
    monkeypatch.setattr(crawler, "datetime", _KstAwareFrozen)
    monkeypatch.setattr(crawler, "SessionLocal", lambda: db)
    monkeypatch.setattr(crawler, "_PAGE_INTERVAL_SEC", 0)
    monkeypatch.setattr(crawler, "_fetch_page",
                        lambda s_, e_, page=1, num_rows=999: calls.append((s_, e_)) or [])
    monkeypatch.setattr(crawler, "_load_registered_bid_nos", lambda db: (set(), True))

    crawler.crawl_recent_openings(days_back=0, max_pages=2)

    # 창 끝이 KST 19:00 이어야 한다 — UTC 10:00 이면 9시간을 놓친다
    assert calls[0][1].endswith("1900"), calls


def test_daily_crawl_task_raises_on_any_failed_window(monkeypatch):
    """정기 크롤은 창이 3개뿐이라 하나만 실패해도 알린다.

    페이지 상한 초과는 "그날 데이터가 잘렸다"는 신호다. 창 격리는 재조회(15창)에
    필요한 정책이지 정기 크롤까지 조용하게 만들라는 뜻이 아니다.
    """
    monkeypatch.setattr(
        crawler, "crawl_recent_openings",
        lambda days_back=2: {"ok": True, "participant_ok": True,
                             "failed_windows": ["202607100000: RuntimeError: page limit"]},
    )
    with pytest.raises(RuntimeError, match="crawl window failed"):
        verification_tasks.daily_crawl_opening_results(days_back=2)


def test_daily_crawl_task_succeeds_when_no_window_failed(monkeypatch):
    monkeypatch.setattr(
        crawler, "crawl_recent_openings",
        lambda days_back=2: {"ok": True, "participant_ok": True, "failed_windows": []},
    )
    assert verification_tasks.daily_crawl_opening_results(days_back=2)["ok"] is True
