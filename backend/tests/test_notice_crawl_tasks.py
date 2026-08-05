"""공고 크롤·정리 Celery 태스크 테스트."""
from datetime import datetime, timedelta
from unittest.mock import patch

from app.db import models
from app.services.crawler import CrawlerService


class _SessionWrapper:
    def __init__(self, real):
        self._real = real

    def __getattr__(self, name):
        if name == "close":
            return lambda: None
        return getattr(self._real, name)


def _patch_session(db_session):
    return patch("app.tasks.notice_crawl_tasks.SessionLocal", lambda: _SessionWrapper(db_session))


def test_crawl_daily_saves_all_categories(db_session):
    from app.tasks.notice_crawl_tasks import crawl_daily_notices

    def fake_fetch(page=1, size=100, category=None, **k):
        if page > 1:
            return []
        item = {"bidNtceNo": f"{category}-{page}", "bidNtceOrd": "00",
                "bidNtceNm": f"{category} 신규공고", "opengDt": "2026-12-31 10:00:00"}
        return [CrawlerService._map_item(item, "CONSTRUCTION")]

    with _patch_session(db_session), \
         patch("app.tasks.notice_crawl_tasks.CrawlerService.fetch_notices", fake_fetch):
        r = crawl_daily_notices(pages=1)

    assert r["saved"] >= 3  # construction/service/goods 각 1건
    assert set(r["by_cat"].keys()) == {"construction", "service", "goods"}


def test_backfill_avalue(db_session):
    from app.tasks.notice_crawl_tasks import backfill_a_values
    now = datetime.now()
    db_session.add(models.Notice(bid_no="BF-1", title="첨부공고", basic_price=1, a_value=0,
                                 attachment_url="http://x/a.hwp", attachment_name="공고규격서.hwp",
                                 end_date=now + timedelta(days=5)))
    db_session.add(models.Notice(bid_no="BF-NOATT", title="첨부없음", basic_price=1, a_value=0,
                                 attachment_url=None, end_date=now + timedelta(days=5)))
    db_session.commit()
    with _patch_session(db_session), \
         patch("app.services.attachment_avalue.AttachmentAValueExtractor.extract",
               lambda url, name=None, **k: {"found": True, "total": 7000000}):
        r = backfill_a_values(limit=10)
    assert r["found"] >= 1
    db_session.expire_all()
    assert db_session.query(models.Notice).filter_by(bid_no="BF-1").first().a_value == 7000000


def test_purge_keeps_referenced_and_recent(db_session):
    from app.tasks.notice_crawl_tasks import purge_old_notices

    now = datetime.now()
    old = now - timedelta(days=200)
    db_session.add_all([
        models.Notice(bid_no="PURGE-OLD-DEL", title="삭제대상", basic_price=1, end_date=old),
        models.Notice(bid_no="PURGE-OLD-KEEP", title="관심참조", basic_price=1, end_date=old),
        models.Notice(bid_no="PURGE-RECENT", title="진행중", basic_price=1, end_date=now + timedelta(days=5)),
    ])
    db_session.add(models.Favorite(bid_no="PURGE-OLD-KEEP"))
    db_session.commit()

    with _patch_session(db_session):
        r = purge_old_notices(days=90)

    db_session.expire_all()
    ids = {n.bid_no for n in db_session.query(models.Notice).all()}
    assert "PURGE-OLD-DEL" not in ids      # 오래된 미참조 → 삭제
    assert "PURGE-OLD-KEEP" in ids         # 관심 참조 → 보존
    assert "PURGE-RECENT" in ids           # 진행중 → 보존
    assert r["deleted"] >= 1


# ─────────────────────────────────────────────────────────────
# 페이지 소진 (2026-08-05 발견)
#
# 공고 목록 API 는 **오래된 순**으로 준다. 5페이지에서 자르면 가장 오래된
# 500건만 매일 반복 수집하고 신규는 한 번도 못 가져온다 — 운영에서
# `construction: {'fetched': 500, 'saved': 0}` 로 드러났다.
# ─────────────────────────────────────────────────────────────

def _paged_fetch(total_pages):
    """total_pages 만큼 꽉 찬 페이지를 주고 그 뒤엔 빈 페이지."""
    seen = []

    def fake_fetch(page=1, size=100, category=None, **k):
        seen.append((category, page))
        if page > total_pages:
            return []
        return [
            CrawlerService._map_item(
                {"bidNtceNo": f"{category}-{page}-{i}", "bidNtceOrd": "00",
                 "bidNtceNm": "공고", "opengDt": "2026-12-31 10:00:00"},
                "CONSTRUCTION")
            for i in range(size)
        ]

    return fake_fetch, seen


def test_crawl_pages_until_exhausted(db_session):
    """고정 5페이지가 아니라 소진할 때까지 넘긴다."""
    from app.tasks.notice_crawl_tasks import crawl_daily_notices

    fake_fetch, seen = _paged_fetch(total_pages=12)
    with _patch_session(db_session), \
         patch("app.tasks.notice_crawl_tasks.CrawlerService.fetch_notices", fake_fetch):
        r = crawl_daily_notices()

    pages_for_cat = [p for c, p in seen if c == "construction"]
    assert max(pages_for_cat) >= 12, f"12페이지까지 못 읽었다: {max(pages_for_cat)}"
    assert r["by_cat"]["construction"]["exhausted"] is True


def test_short_page_stops_early(db_session):
    """마지막 페이지(size 미만)를 만나면 멈춘다 — 빈 페이지까지 안 가도 된다."""
    from app.tasks.notice_crawl_tasks import crawl_daily_notices

    def fake_fetch(page=1, size=100, category=None, **k):
        n = size if page < 3 else 7      # 3페이지가 마지막
        return [
            CrawlerService._map_item(
                {"bidNtceNo": f"{category}-{page}-{i}", "bidNtceOrd": "00",
                 "bidNtceNm": "공고", "opengDt": "2026-12-31 10:00:00"},
                "CONSTRUCTION")
            for i in range(n)
        ]

    with _patch_session(db_session), \
         patch("app.tasks.notice_crawl_tasks.CrawlerService.fetch_notices", fake_fetch):
        r = crawl_daily_notices()

    assert r["by_cat"]["construction"]["fetched"] == 100 + 100 + 7
    assert r["by_cat"]["construction"]["exhausted"] is True


def test_cap_is_reported_not_silent(db_session):
    """상한에 닿으면 exhausted=False 로 알린다 — 조용한 절삭 금지."""
    from app.tasks.notice_crawl_tasks import crawl_daily_notices

    fake_fetch, _ = _paged_fetch(total_pages=999)
    with _patch_session(db_session), \
         patch("app.tasks.notice_crawl_tasks.CrawlerService.fetch_notices", fake_fetch):
        r = crawl_daily_notices(max_pages=3)

    assert r["by_cat"]["construction"]["exhausted"] is False
    assert r["by_cat"]["construction"]["fetched"] == 300


def test_explicit_pages_still_honored(db_session):
    """수동 조회용으로 pages 를 주면 그만큼만 읽는다."""
    from app.tasks.notice_crawl_tasks import crawl_daily_notices

    fake_fetch, _ = _paged_fetch(total_pages=999)
    with _patch_session(db_session), \
         patch("app.tasks.notice_crawl_tasks.CrawlerService.fetch_notices", fake_fetch):
        r = crawl_daily_notices(pages=2)

    assert r["by_cat"]["construction"]["fetched"] == 200
