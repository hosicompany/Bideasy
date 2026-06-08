"""
자격 맞춤 추천 Celery 태스크 (웹 전용 차별화)
=====================================
신규 공고를 활성 사용자의 프로필(면허·지역)과 매칭해, 입찰 가능한 신규
공고를 인앱 알림으로 능동 제안한다. 익스텐션이 못 주는 "발견·추천" 가치.

스케줄 (celery_app.py beat_schedule):
- 매일 07:00 KST: recommend.send_matches
  → 최근 1일 신규 공고 ↔ 프로필 보유 사용자 매칭 → "맞춤 공고 N건" 알림

매칭 기준 (targeted): QualificationChecker PASS + 긍정 뱃지(지역적합/면허보유).
단순 "제한없음"이 아니라 사용자 프로필에 실제로 부합하는 공고만 추천.
"""
from datetime import datetime, timedelta

from sqlalchemy import or_, and_

from app.core.celery_app import celery_app
from app.core.logging import get_logger
from app.db import models
from app.db.session import SessionLocal
from app.services.qualification_checker import QualificationChecker

logger = get_logger(__name__)

_POSITIVE_BADGES = {"지역적합", "면허보유"}
_MAX_NEW_NOTICES = 2000


def _positive_match(notice, user) -> bool:
    """프로필에 실제 부합하는지 — PASS + 긍정 뱃지(지역/면허)."""
    check = {
        "bidNtceNm": notice.title or "",
        "LmtRegion": getattr(notice, "region", "") or "",
        "bidNtceNo": notice.bid_no,
    }
    r = QualificationChecker.check_qualification(check, user)
    if r.get("status") != "PASS":
        return False
    return any(b in _POSITIVE_BADGES for b in r.get("details", []))


@celery_app.task(name="recommend.send_matches")
def send_recommendations() -> dict:
    """신규 공고 ↔ 프로필 보유 사용자 매칭 → 맞춤 추천 알림."""
    db = SessionLocal()
    results = {"users_notified": 0, "users_checked": 0, "new_notices": 0}
    try:
        now = datetime.now()
        since = now - timedelta(days=1)
        new_notices = (
            db.query(models.Notice)
            .filter(
                models.Notice.start_date >= since,
                models.Notice.end_date > now,
                ~models.Notice.title.like("[Mock]%"),
            )
            .limit(_MAX_NEW_NOTICES)
            .all()
        )
        results["new_notices"] = len(new_notices)
        if not new_notices:
            logger.info("[recommend.send_matches] no new notices")
            return results

        # 프로필(면허 또는 지역) 보유 사용자만 대상
        users = (
            db.query(models.User)
            .filter(or_(
                and_(models.User.licenses.isnot(None), models.User.licenses != ""),
                and_(models.User.location.isnot(None), models.User.location != ""),
            ))
            .all()
        )
        today = now.date().isoformat()

        for u in users:
            results["users_checked"] += 1
            noti_type = f"REC_{today}"
            # 하루 1회 (중복 방지)
            exists = (
                db.query(models.Notification.id)
                .filter(models.Notification.user_id == u.id, models.Notification.noti_type == noti_type)
                .first()
            )
            if exists:
                continue
            matched = [n for n in new_notices if _positive_match(n, u)]
            if not matched:
                continue
            db.add(models.Notification(
                user_id=u.id,
                title=f"🎯 맞춤 공고 {len(matched)}건",
                body=f"회원님 자격으로 입찰 가능한 신규 공고 {len(matched)}건이 올라왔어요.",
                noti_type=noti_type,
                data_json={"bid_nos": [n.bid_no for n in matched[:5]], "count": len(matched)},
                is_read=0,
            ))
            results["users_notified"] += 1

        db.commit()
        logger.info(f"[recommend.send_matches] {results}")
        return results
    except Exception as e:
        db.rollback()
        logger.error(f"[recommend.send_matches] error: {e}", exc_info=True)
        return {"error": str(e), **results}
    finally:
        db.close()
