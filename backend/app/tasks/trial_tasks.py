"""
체험(Trial) 만료 알림 Celery 태스크
=====================================
14일 Pro 체험 사용자에게 만료 임박·만료 알림을 자동 발송.

스케줄 (celery_app.py beat_schedule):
- 매일 10:00 KST: trial.send_expiry_reminders
  → 3일 후 만료 / 1일 후 만료 / 어제 만료된 사용자 식별 → Notification 생성

알림 종류:
- TRIAL_EXPIRING_SOON_3D (Pro 체험 3일 남음 — 결제 유도)
- TRIAL_EXPIRING_SOON_1D (Pro 체험 1일 남음 — 결제 유도)
- TRIAL_EXPIRED (만료됨 — Win-back 7일 한정 첫달 50% 할인)
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, or_

from app.core.celery_app import celery_app
from app.core.logging import get_logger
from app.db import models
from app.db.session import SessionLocal

logger = get_logger(__name__)


# 알림 제목·본문 템플릿
_TEMPLATES = {
    "TRIAL_EXPIRING_3D": (
        "Pro 체험이 3일 남았어요 🎁",
        "지금 결제하시면 첫 달 50% 할인 — Pro 24,900원 → 12,450원.",
    ),
    "TRIAL_EXPIRING_1D": (
        "Pro 체험이 내일 끝나요 ⏰",
        "AI 분석·Deep Analysis 등 Pro 기능이 일일 한도로 제한됩니다. 지금 결제 시 첫 달 50% 할인.",
    ),
    "TRIAL_EXPIRED": (
        "Pro 체험이 끝났습니다",
        "체험 만료 후 7일 이내 결제 시 첫 달 50% 할인 — 12,450원에 Pro 한 달 더 사용해보세요.",
    ),
}


def _has_notification(db, user_id: int, noti_type: str) -> bool:
    """동일 유형의 알림이 이미 있는지 — 중복 발송 방지."""
    exists = (
        db.query(models.Notification.id)
        .filter(
            models.Notification.user_id == user_id,
            models.Notification.noti_type == noti_type,
        )
        .first()
    )
    return exists is not None


def _create_trial_notification(db, user_id: int, noti_type: str) -> bool:
    """Notification 1건 생성. 이미 있으면 False, 새로 만들었으면 True."""
    if _has_notification(db, user_id, noti_type):
        return False

    title, body = _TEMPLATES[noti_type]
    noti = models.Notification(
        user_id=user_id,
        title=title,
        body=body,
        noti_type=noti_type,
        data_json={"trial_event": noti_type},
        is_read=0,
    )
    db.add(noti)
    return True


@celery_app.task(name="trial.send_expiry_reminders")
def send_expiry_reminders() -> dict:
    """
    매일 10:00 KST 실행. 활성 체험 사용자 중:
      - 정확히 3일 후 만료 → TRIAL_EXPIRING_3D
      - 정확히 1일 후 만료 → TRIAL_EXPIRING_1D
      - 어제 만료 (만료 후 0~1일) → TRIAL_EXPIRED

    중복 방지: 같은 noti_type 알림이 이미 있으면 건너뜀.
    """
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        three_days_later = now + timedelta(days=3)
        one_day_later = now + timedelta(days=1)
        yesterday = now - timedelta(days=1)

        results = {"3d": 0, "1d": 0, "expired": 0, "skipped": 0}

        # ── 3일 후 만료 사용자 ──────────────────────────────
        # 윈도우: now+2.5d ~ now+3.5d (10시 실행이라 ±12h 여유)
        users_3d = (
            db.query(models.User)
            .filter(
                models.User.trial_expires_at.isnot(None),
                models.User.trial_expires_at >= three_days_later - timedelta(hours=12),
                models.User.trial_expires_at < three_days_later + timedelta(hours=12),
                # 유료 구독자는 알림 제외
                or_(
                    models.User.subscription_expires_at.is_(None),
                    models.User.subscription_expires_at < now,
                ),
                models.User.tier == "free",
            )
            .all()
        )
        for u in users_3d:
            if _create_trial_notification(db, u.id, "TRIAL_EXPIRING_3D"):
                results["3d"] += 1
            else:
                results["skipped"] += 1

        # ── 1일 후 만료 사용자 ──────────────────────────────
        users_1d = (
            db.query(models.User)
            .filter(
                models.User.trial_expires_at.isnot(None),
                models.User.trial_expires_at >= one_day_later - timedelta(hours=12),
                models.User.trial_expires_at < one_day_later + timedelta(hours=12),
                or_(
                    models.User.subscription_expires_at.is_(None),
                    models.User.subscription_expires_at < now,
                ),
                models.User.tier == "free",
            )
            .all()
        )
        for u in users_1d:
            if _create_trial_notification(db, u.id, "TRIAL_EXPIRING_1D"):
                results["1d"] += 1
            else:
                results["skipped"] += 1

        # ── 어제 만료된 사용자 (Win-back) ───────────────────
        users_expired = (
            db.query(models.User)
            .filter(
                models.User.trial_expires_at.isnot(None),
                models.User.trial_expires_at >= yesterday - timedelta(hours=12),
                models.User.trial_expires_at < yesterday + timedelta(hours=12),
                or_(
                    models.User.subscription_expires_at.is_(None),
                    models.User.subscription_expires_at < now,
                ),
                models.User.tier == "free",
            )
            .all()
        )
        for u in users_expired:
            if _create_trial_notification(db, u.id, "TRIAL_EXPIRED"):
                results["expired"] += 1
            else:
                results["skipped"] += 1

        db.commit()
        logger.info(f"[trial.send_expiry_reminders] {results}")
        return results
    except Exception as e:
        db.rollback()
        logger.error(f"[trial.send_expiry_reminders] error: {e}", exc_info=True)
        return {"error": str(e)}
    finally:
        db.close()
