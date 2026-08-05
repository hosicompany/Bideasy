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
def crawl_daily_notices(pages: int | None = None, max_pages: int = 60) -> dict:
    """공사/용역/물품 신규 공고를 카테고리별로 긁어 누적 DB 에 적재.

    ⚠️ **페이지를 고정 개수로 자르면 안 된다** (2026-08-05 실측).
    이 API 는 **오래된 순**으로 준다:

        p1  = 2026-07-31 07:48   ← 이미 다 갖고 있는 구간
        p16 = 2026-08-05 16:22   ← 오늘 신규

    예전엔 5페이지(500건)에서 잘랐는데, 조회창(최근 5일) 실제 물량이 공사만
    1,600건이라 **가장 오래된 500건만 매일 반복 수집**하고 신규는 한 번도
    못 가져왔다(`construction: {'fetched': 500, 'saved': 0}`).
    그 여파로 기초금액 매칭이 `no_notice` 로 새고, 모의투찰 후보도 줄었다.

    그래서 **소진할 때까지** 페이지를 넘긴다. 페이지 간 중복은 없고(실측),
    17페이지로 전량이 나온다. `max_pages` 는 폭주 방지용 상한이며, 상한에
    닿으면 **로그로 알린다** — 조용한 절삭 금지.

    Args:
        pages: (구) 카테고리당 고정 페이지 수. 주면 그만큼만 읽는다(수동 조회용).
        max_pages: 소진 모드의 안전 상한.
    """
    db = SessionLocal()
    result = {"fetched": 0, "saved": 0, "by_cat": {}}
    new_bid_nos: list[str] = []
    try:
        limit = pages if pages else max_pages
        for cat in CRAWL_CATEGORIES:
            cat_fetched = cat_saved = 0
            exhausted = False
            for page in range(1, limit + 1):
                items = CrawlerService.fetch_notices(page=page, size=100, category=cat)
                if not items:
                    exhausted = True
                    break  # 더 없음 → 다음 카테고리
                cat_fetched += len(items)
                # 적재 전 기존 bid_no 를 확인해 "이번에 새로 생긴 것"만 추린다.
                # (save_notices 는 건수만 돌려주고, 반환형을 바꾸면 호출처 5곳이 깨진다)
                incoming = [d.get("bid_no") for d in items if d.get("bid_no")]
                existing = {
                    row[0]
                    for row in db.query(models.Notice.bid_no)
                    .filter(models.Notice.bid_no.in_(incoming))
                    .all()
                } if incoming else set()
                cat_saved += CrawlerService.save_notices(db, items)
                new_bid_nos.extend(b for b in incoming if b not in existing)
                # 마지막 페이지는 size 미만으로 온다 — 소진 신호
                if len(items) < 100:
                    exhausted = True
                    break
            if not exhausted:
                # 상한에 닿았다 = 아직 남았는데 못 읽었다. 조용히 넘기지 않는다.
                logger.warning(
                    f"[notices.crawl_daily] {cat}: {limit}페이지 상한에 닿았다 "
                    f"— 남은 공고를 못 읽었을 수 있다(fetched={cat_fetched})."
                )
            result["by_cat"][cat] = {
                "fetched": cat_fetched, "saved": cat_saved, "exhausted": exhausted,
            }
            result["fetched"] += cat_fetched
            result["saved"] += cat_saved
        logger.info(f"[notices.crawl_daily] {result}")

        # 색인 통보(best-effort) — 신규 공고 URL 을 네이버·Bing 에 알린다.
        # 수집은 이미 커밋됐으므로 통보 실패가 수집을 되돌리지 않는다.
        from app.services import indexnow
        result["indexnow"] = indexnow.submit(
            indexnow.notice_urls(new_bid_nos), reason="crawl_daily"
        )
        return result
    except Exception as e:
        db.rollback()
        logger.error(f"[notices.crawl_daily] error: {e}", exc_info=True)
        return {"error": str(e), **result}
    finally:
        db.close()


@celery_app.task(name="notices.backfill_avalue")
def backfill_a_values(limit: int = 50) -> dict:
    """A값 Tier 2 백필 — 첨부 있고 a_value 없는 진행중 공고의 A값을 파싱.

    매일 소량(limit)씩 처리. 다운로드+파싱이라 건당 수 초 → 배치 제한.
    """
    db = SessionLocal()
    from app.services.attachment_avalue import AttachmentAValueExtractor
    result = {"checked": 0, "found": 0}
    try:
        now = datetime.now()
        notices = (
            db.query(models.Notice)
            .filter(
                (models.Notice.a_value == 0) | (models.Notice.a_value.is_(None)),
                models.Notice.attachment_url.isnot(None),
                models.Notice.attachment_url != "",
                models.Notice.end_date > now,
            )
            .limit(limit)
            .all()
        )
        for n in notices:
            result["checked"] += 1
            r = AttachmentAValueExtractor.extract(n.attachment_url, n.attachment_name)
            if r.get("found") and r.get("total"):
                n.a_value = int(r["total"])
                result["found"] += 1
                db.commit()
        logger.info(f"[notices.backfill_avalue] {result}")
        return result
    except Exception as e:
        db.rollback()
        logger.error(f"[notices.backfill_avalue] error: {e}", exc_info=True)
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


@celery_app.task(name="notices.crawl_basis_amount")
def crawl_basis_amount(days_back: int = 3) -> dict:
    """공사 기초금액 수집 — 목록 API 가 안 주는 `bssamt` 를 전용 오퍼레이션에서.

    같은 응답에 A값 구성요소도 있어 tier0 로 함께 채운다.
    상세·주의사항: `services/basis_amount_crawler.py`
    """
    from app.services.basis_amount_crawler import crawl_recent

    return crawl_recent(days_back=days_back)
