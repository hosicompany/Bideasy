"""
마감 추적 리마인더 Celery 태스크
=====================================
사용자가 추적(BidTrack)하는 공고의 마감(개찰)이 임박하면 인앱 알림 생성.

스케줄 (celery_app.py beat_schedule):
- 매일 10:00 KST: deadline.send_reminders
  → 추적 공고 중 D-3 / D-1 / 당일(D-day) → Notification 생성 (중복 방지)
"""
from datetime import datetime, timedelta

from app.core.celery_app import celery_app
from app.core.logging import get_logger
from app.db import models
from app.db.session import SessionLocal

logger = get_logger(__name__)

# (라벨, 잔여일 하한(포함), 잔여일 상한(미만)) — 일 단위. 10시 실행 ±12h 여유.
_WINDOWS = [
    ("D3", 2.5, 3.5),
    ("D1", 0.5, 1.5),
    ("DDAY", -0.01, 0.5),
]


def _has_notification(db, user_id: int, noti_type: str) -> bool:
    return (
        db.query(models.Notification.id)
        .filter(
            models.Notification.user_id == user_id,
            models.Notification.noti_type == noti_type,
        )
        .first()
        is not None
    )


@celery_app.task(name="deadline.send_reminders")
def send_deadline_reminders() -> dict:
    """추적 공고 마감 임박 알림 (D-3/D-1/당일)."""
    db = SessionLocal()
    results = {"D3": 0, "D1": 0, "DDAY": 0, "skipped": 0}
    try:
        now = datetime.now()
        rows = (
            db.query(models.BidTrack, models.Notice)
            .join(models.Notice, models.BidTrack.bid_no == models.Notice.bid_no)
            .filter(
                models.BidTrack.remind.is_(True),
                models.Notice.end_date.isnot(None),
                models.Notice.end_date > now - timedelta(days=1),
            )
            .all()
        )
        for track, notice in rows:
            remaining_days = (notice.end_date - now).total_seconds() / 86400.0
            for label, lo, hi in _WINDOWS:
                if lo <= remaining_days < hi:
                    noti_type = f"DEADLINE_{label}_{notice.bid_no}"
                    if _has_notification(db, track.user_id, noti_type):
                        results["skipped"] += 1
                        break
                    when = {"D3": "3일 후", "D1": "내일", "DDAY": "오늘"}[label]
                    db.add(models.Notification(
                        user_id=track.user_id,
                        title=f"⏰ 마감 임박: {when} 개찰",
                        body=f"추적 중인 '{(notice.title or notice.bid_no)[:40]}' 개찰이 {when}입니다.",
                        noti_type=noti_type,
                        data_json={"bid_no": notice.bid_no, "deadline": label},
                        is_read=0,
                    ))
                    results[label] += 1
                    break
        db.commit()
        logger.info(f"[deadline.send_reminders] {results}")
        return results
    except Exception as e:
        db.rollback()
        logger.error(f"[deadline.send_reminders] error: {e}", exc_info=True)
        return {"error": str(e), **results}
    finally:
        db.close()
