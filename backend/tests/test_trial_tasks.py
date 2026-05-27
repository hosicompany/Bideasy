"""Trial 만료 알림 Celery 태스크 테스트."""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from app.db import models
from app.tasks.trial_tasks import send_expiry_reminders


def _trial_user(db, email: str, expires_in_days: float, tier: str = "free") -> models.User:
    """체험 expires_at 이 N일 후/전 인 사용자 생성."""
    user = models.User(
        email=email,
        hashed_password="x",
        tier=tier,
        trial_started_at=datetime.now(timezone.utc) - timedelta(days=14 - expires_in_days),
        trial_expires_at=datetime.now(timezone.utc) + timedelta(days=expires_in_days),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _patch_session(db_session):
    """celery task 내부의 SessionLocal() 호출을 fixture db_session 으로 대체."""
    class _CM:
        def __enter__(self_inner):
            return db_session

        def __exit__(self_inner, *a):
            pass

    # SessionLocal() 호출 → db_session 반환 (close 는 no-op)
    return patch("app.tasks.trial_tasks.SessionLocal", lambda: _SessionWrapper(db_session))


class _SessionWrapper:
    """SessionLocal() 가 호출 가능한 객체를 반환하므로, .close() / .commit() 등을 db_session 에 위임."""
    def __init__(self, real):
        self._real = real

    def __getattr__(self, name):
        # close 는 fixture 가 처리하므로 no-op
        if name == "close":
            return lambda: None
        return getattr(self._real, name)


def test_send_reminders_creates_3d_notification(db_session):
    """3일 후 만료 사용자에게 TRIAL_EXPIRING_3D 생성."""
    user = _trial_user(db_session, "exp-3d@test.com", expires_in_days=3)
    with _patch_session(db_session):
        result = send_expiry_reminders()

    assert result["3d"] >= 1

    noti = (
        db_session.query(models.Notification)
        .filter(models.Notification.user_id == user.id)
        .first()
    )
    assert noti is not None
    assert noti.noti_type == "TRIAL_EXPIRING_3D"
    assert "3일" in noti.title


def test_send_reminders_creates_1d_notification(db_session):
    user = _trial_user(db_session, "exp-1d@test.com", expires_in_days=1)
    with _patch_session(db_session):
        result = send_expiry_reminders()

    assert result["1d"] >= 1
    noti = (
        db_session.query(models.Notification)
        .filter(models.Notification.user_id == user.id)
        .first()
    )
    assert noti is not None
    assert noti.noti_type == "TRIAL_EXPIRING_1D"


def test_send_reminders_creates_expired_notification(db_session):
    """어제 만료된 사용자에게 win-back 알림."""
    user = _trial_user(db_session, "exp-yesterday@test.com", expires_in_days=-1)
    with _patch_session(db_session):
        result = send_expiry_reminders()

    assert result["expired"] >= 1
    noti = (
        db_session.query(models.Notification)
        .filter(models.Notification.user_id == user.id)
        .first()
    )
    assert noti is not None
    assert noti.noti_type == "TRIAL_EXPIRED"


def test_send_reminders_skips_paid_subscribers(db_session):
    """유료 구독 사용자는 알림 제외."""
    user = models.User(
        email="paid-trial@test.com",
        hashed_password="x",
        tier="pro",  # 유료
        subscription_expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        trial_started_at=datetime.now(timezone.utc) - timedelta(days=11),
        trial_expires_at=datetime.now(timezone.utc) + timedelta(days=3),
    )
    db_session.add(user)
    db_session.commit()

    with _patch_session(db_session):
        send_expiry_reminders()

    noti = (
        db_session.query(models.Notification)
        .filter(models.Notification.user_id == user.id)
        .first()
    )
    assert noti is None  # 유료 구독자에겐 발송 안 됨


def test_send_reminders_idempotent(db_session):
    """두 번 실행해도 중복 알림 생성 안 함."""
    user = _trial_user(db_session, "idem@test.com", expires_in_days=3)

    with _patch_session(db_session):
        send_expiry_reminders()
        send_expiry_reminders()  # 두 번째 호출

    count = (
        db_session.query(models.Notification)
        .filter(
            models.Notification.user_id == user.id,
            models.Notification.noti_type == "TRIAL_EXPIRING_3D",
        )
        .count()
    )
    assert count == 1


def test_send_reminders_no_eligible_users(db_session):
    """대상 사용자 없으면 0건 반환."""
    # 가입만 했지만 trial 만료가 5일 후 — 3일/1일 알림 윈도우에 안 잡힘
    _trial_user(db_session, "out-of-window@test.com", expires_in_days=5)

    with _patch_session(db_session):
        result = send_expiry_reminders()

    assert result["3d"] == 0
    assert result["1d"] == 0
    assert result["expired"] == 0
