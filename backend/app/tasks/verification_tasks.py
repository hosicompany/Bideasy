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
    # 정기 크롤은 **창이 3개뿐**이고 다음 날 창이 겹쳐 자기 치유되므로, 한 창만
    # 실패해도 시끄럽게 알린다. 특히 페이지 상한 초과는 "그날 데이터가 잘렸다"는
    # 신호인데, 이걸 삼키면 성수기마다 조용히 결손이 쌓인다.
    # (표적 재조회는 창이 15개라 정책이 다르다 — 거긴 전 창 실패만 실패로 본다.)
    if result.get("failed_windows"):
        raise RuntimeError(f"crawl window failed: {result['failed_windows']}")
    # 참가자 수집 전면 실패는 성공으로 삼키지 않는다. 낙찰 결과는 이미 커밋됐고
    # 되돌리지 않지만(부가 데이터라 본 크롤을 막지 않는다는 설계), 태스크는
    # FAILURE 로 남겨야 한다 — 안 그러면 등수 지표가 조용히 성장 정지한 채
    # 크롤은 매일 초록불이고 화면은 "참가자 데이터 대기"와 구분되지 않는다.
    if not result.get("participant_ok", True):
        raise RuntimeError(f"participant collection failed: {result}")
    return result


@celery_app.task(name="verification.recheck_pending_openings")
def recheck_pending_openings(max_days: int = 21, max_dates: int = 21) -> dict:
    """심야 — 채점 대기 중인 등록 공고의 **개찰일을 표적 재조회**.

    정기 크롤(19:00, 개찰일 기준 2일 창)은 개찰 당일만 본다. 그런데 개찰은
    마감 당일에 나도 **낙찰자 확정(적격심사)은 며칠~수주** 걸리고, 크롤러는
    낙찰자 행만 `OpeningResult` 로 저장하므로 2일 창 안에 확정되지 않은 공고는
    **영영 결과가 안 붙는다**. 실측 2026-08-13: 채점 도달률이 마감 후 8~9일이
    지나도 33.8% 에서 정체(NO_RESULT 1,747공고 중 개찰 결과 보유 **0건**).

    개찰 API 는 날짜 창 조회만 지원해(공고번호 지정 시 "필수값 입력 에러",
    같이 줘도 무시) 그 날짜를 통째로 훑는 수밖에 없다.

    `max_dates` 는 **후보 날짜 수보다 작으면 안 된다.** 대상보다 작게 잡고 오래된
    순으로만 처리하면 새 날짜가 뒤로 밀려, 수확이 가장 큰 D+3~D+7 구간을 정확히
    비켜간다. 후보 창은 `max_days=21` 일 때 **22 캘린더일**(경계 포함)이고 그 안의
    평일은 **16일**이라, 15 로 두면 정상 운영에서 매일 밤 잘림 경고가 뜬다 —
    매일 뜨는 경보는 곧 무시된다. 이미 걷힌 날짜는 대상에서 자동으로 빠지므로
    넉넉히 잡아도 실제 조회는 남은 날짜 수만큼이다.

    실패해도 정기 크롤과 독립이다 — 이건 **보충**이지 본 수집이 아니다.
    창 하나가 실패해도 나머지 날짜는 처리된다(창 단위 격리).
    """
    from app.db.session import SessionLocal
    from app.services.mock_bidding import pending_opening_dates
    from app.services.opening_result_crawler import (
        crawl_recent_openings, windows_for_dates,
    )

    db = SessionLocal()
    try:
        dates, deferred = pending_opening_dates(db, max_days=max_days, limit=max_dates)
    finally:
        db.close()

    if not dates:
        logger.info("[recheck_openings] 재조회 대상 없음")
        return {"ok": True, "dates": 0, "deferred": deferred,
                "note": "재조회 대상 없음"}

    logger.info(f"[recheck_openings] 대상 {len(dates)}일: "
                f"{dates[0].isoformat()} ~ {dates[-1].isoformat()}")
    result = crawl_recent_openings(windows=windows_for_dates(dates))
    result["recheck_dates"] = [d.isoformat() for d in dates]
    # 밀린 날짜가 계속 잡히면 `max_dates` 가 실제 대상보다 작다는 뜻이다.
    result["deferred"] = deferred
    logger.info(f"[recheck_openings] {result}")
    if not result.get("ok"):
        raise RuntimeError(result.get("error", "recheck crawl failed"))
    # 정기 크롤과 **같은 계약**을 지킨다. 이걸 빼면 `_load_registered_bid_nos` 가
    # 죽었을 때 수천 페이지를 다 훑고 참가자 0건 저장한 뒤 초록불로 끝난다 —
    # 적격검사 완료로 sucsf_yn·rank 가 갱신되는 게 재조회의 실질 산출물인데.
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
