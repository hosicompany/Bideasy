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
