"""
일일 검증 Celery 태스크
========================
매일 자동으로 다음 작업 수행:
1. 어제 개찰된 공사 입찰 결과 크롤 → opening_results 테이블 적재
2. 우리가 분석했던 (notices 에 있는) 공고 중 개찰된 것 → 추천 vs 실 결과 비교
3. predictions_log.jsonl 에 누적
4. 매주 자가보정 사이클 (weekly-strategy-recalibration) 이 이 로그를 학습 입력으로 사용

타임존: celery_app.py 가 Asia/Seoul 이므로 schedule 의 hour 는 KST.
"""

from datetime import datetime, timedelta
from pathlib import Path

from app.core.celery_app import celery_app
from app.core.logging import get_logger
from app.db import models
from app.db.session import SessionLocal

logger = get_logger(__name__)


@celery_app.task(name="verification.daily_crawl_opening_results")
def daily_crawl_opening_results(days_back: int = 2) -> dict:
    """매일 19:00 KST — 최근 N일 개찰결과를 DB 에 적재."""
    # 지연 import (Celery worker 부팅 가속)
    from app.services.opening_result_crawler import crawl_recent_openings

    result = crawl_recent_openings(days_back=days_back)
    logger.info(f"[daily_crawl] {result}")
    if not result.get("ok"):
        raise RuntimeError(result.get("error", "opening result crawl failed"))
    # 참가자 수집 전면 실패는 성공으로 삼키지 않는다. 낙찰 결과는 이미 커밋됐고
    # 되돌리지 않지만(부가 데이터라 본 크롤을 막지 않는다는 설계), 태스크는
    # FAILURE 로 남겨야 한다 — 안 그러면 등수 지표가 조용히 성장 정지한 채
    # 크롤은 매일 초록불이고 화면은 "참가자 데이터 대기"와 구분되지 않는다.
    if not result.get("participant_ok", True):
        raise RuntimeError(f"participant collection failed: {result}")
    return result


@celery_app.task(name="opening_stats.rebuild")
def rebuild_opening_stats(window_days: int = 365) -> dict:
    """매일 19:30 KST — 누적 개찰 통계 재집계.

    개찰 크롤(19:00) 뒤에 둔다. 앞이 실패해도 이건 어제까지의 원장으로 돌아
    통계가 통째로 비지는 않는다(원장이 곧 소스라 재집계는 언제 돌려도 안전).
    """
    from app.services.opening_stats import rebuild

    db = SessionLocal()
    try:
        result = rebuild(db, window_days=window_days)
        logger.info(f"[opening_stats] {result}")
        return result
    except Exception as e:  # noqa: BLE001
        db.rollback()
        logger.error(f"[opening_stats] error: {e}", exc_info=True)
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
    finally:
        db.close()


@celery_app.task(name="verification.daily_verify_predictions")
def daily_verify_predictions(days_back: int = 30, limit: int = 500) -> dict:
    """매일 20:00 KST — 최근 N일 개찰 지난 notices 에 대해 추천 vs 실 결과 비교."""
    from app.services.prediction_verifier import verify_notices

    now = datetime.now()
    cutoff = now - timedelta(days=days_back)
    log_path = Path(__file__).resolve().parent.parent.parent / "data" / "predictions_log.jsonl"

    db = SessionLocal()
    try:
        notices = db.query(models.Notice).filter(
            models.Notice.end_date < now,
            models.Notice.end_date > cutoff,
        ).limit(limit).all()
        logger.info(f"[daily_verify] {len(notices)} candidates")

        summary = verify_notices(db, notices, log_path=log_path)
        # 결과 클래스 정리 (results 는 너무 길어 로그에서 제외)
        compact = {k: v for k, v in summary.items() if k != "results"}
        logger.info(f"[daily_verify] {compact}")
        return compact
    finally:
        db.close()
