"""
공고 크롤·정리 Celery 태스크
================================
매일 신규 입찰공고를 누적 notices 테이블에 적재해 검색 재현율을 높이고,
월 1회 오래된 마감 공고를 정리(purge)해 테이블을 경량 유지한다.

스케줄 (celery_app.py beat_schedule):
- 매일 06:00 KST: notices.crawl_daily — 공사/용역/물품 신규 공고 적재
- 매월 1일 05:00 KST: notices.purge_old — 마감 N일 경과 공고 삭제
  (단, 사용자 참조(관심·입찰·AI분석·포인트)된 공고는 보존 → FK 무결성)
"""
from datetime import datetime, timedelta

from app.core.celery_app import celery_app
from app.core.logging import get_logger
from app.db import models
from app.db.session import SessionLocal
from app.services.crawler import CrawlerService

logger = get_logger(__name__)

CRAWL_CATEGORIES = ("construction", "service", "goods")
PURGE_AFTER_DAYS = 90  # 마감 지난 지 90일 넘으면 정리 대상


@celery_app.task(name="notices.crawl_daily")
def crawl_daily_notices(pages: int = 5) -> dict:
    """공사/용역/물품 신규 공고를 카테고리별로 긁어 누적 DB 에 적재.

    pages: 카테고리당 조회 페이지 수 (page당 100건). 3 × pages × 100 상한.
    save_notices 가 bid_no 로 중복 스킵하므로 신규분만 적재.
    """
    db = SessionLocal()
    result = {"fetched": 0, "saved": 0, "by_cat": {}}
    try:
        for cat in CRAWL_CATEGORIES:
            cat_fetched = cat_saved = 0
            for page in range(1, pages + 1):
                items = CrawlerService.fetch_notices(page=page, size=100, category=cat)
                if not items:
                    break  # 더 없음 → 다음 카테고리
                cat_fetched += len(items)
                cat_saved += CrawlerService.save_notices(db, items)
            result["by_cat"][cat] = {"fetched": cat_fetched, "saved": cat_saved}
            result["fetched"] += cat_fetched
            result["saved"] += cat_saved
        logger.info(f"[notices.crawl_daily] {result}")
        return result
    except Exception as e:
        db.rollback()
        logger.error(f"[notices.crawl_daily] error: {e}", exc_info=True)
        return {"error": str(e), **result}
    finally:
        db.close()


@celery_app.task(name="notices.purge_old")
def purge_old_notices(days: int = PURGE_AFTER_DAYS) -> dict:
    """마감(end_date) 지난 지 days 일 넘은 공고 삭제 — 테이블 경량화.

    사용자가 참조한 공고(관심·입찰·AI분석·포인트)는 FK 무결성·데이터 보존
    위해 삭제 제외.
    """
    db = SessionLocal()
    try:
        cutoff = datetime.now() - timedelta(days=days)

        # 참조된 bid_no 수집 (삭제 제외 대상)
        referenced = set()
        for col in (
            models.Favorite.bid_no,
            models.UserBid.notice_id,
            models.AIAnalysisLog.bid_no,
            models.PointTransaction.bid_no,
        ):
            referenced.update(row[0] for row in db.query(col).distinct() if row[0])

        q = db.query(models.Notice).filter(
            models.Notice.end_date.isnot(None),
            models.Notice.end_date < cutoff,
        )
        if referenced:
            q = q.filter(~models.Notice.bid_no.in_(referenced))
        deleted = q.delete(synchronize_session=False)
        db.commit()
        logger.info(
            f"[notices.purge_old] deleted={deleted} cutoff={cutoff.date()} "
            f"kept_referenced={len(referenced)}"
        )
        return {"deleted": deleted, "kept_referenced": len(referenced)}
    except Exception as e:
        db.rollback()
        logger.error(f"[notices.purge_old] error: {e}", exc_info=True)
        return {"error": str(e)}
    finally:
        db.close()
