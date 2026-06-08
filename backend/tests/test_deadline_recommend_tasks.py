"""마감 리마인더 + 자격 맞춤 추천 Celery 태스크 테스트."""
from datetime import datetime, timedelta
from unittest.mock import patch

from app.db import models


class _SessionWrapper:
    def __init__(self, real):
        self._real = real

    def __getattr__(self, name):
        if name == "close":
            return lambda: None
        return getattr(self._real, name)


def _user(db, email, **kw):
    u = models.User(email=email, hashed_password="x", **kw)
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def test_deadline_reminder_d1(db_session):
    from app.tasks.deadline_tasks import send_deadline_reminders

    u = _user(db_session, "track@test.com")
    now = datetime.now()
    db_session.add(models.Notice(bid_no="TRK-D1", title="추적 공고", basic_price=1,
                                 end_date=now + timedelta(days=1)))
    db_session.add(models.BidTrack(user_id=u.id, bid_no="TRK-D1", remind=True))
    db_session.commit()

    with patch("app.tasks.deadline_tasks.SessionLocal", lambda: _SessionWrapper(db_session)):
        r = send_deadline_reminders()

    assert r["D1"] >= 1
    noti = (
        db_session.query(models.Notification)
        .filter(models.Notification.user_id == u.id,
                models.Notification.noti_type == "DEADLINE_D1_TRK-D1")
        .first()
    )
    assert noti is not None and "내일" in noti.title


def test_recommendation_matches_license(db_session):
    from app.tasks.recommendation_tasks import send_recommendations

    # 전기공사업 보유 사용자 + 제목에 '전기' 포함 신규 공고 → 면허보유 매칭
    u = _user(db_session, "rec@test.com", licenses="전기공사업")
    now = datetime.now()
    db_session.add(models.Notice(bid_no="REC-MATCH", title="전기 설비 공사", basic_price=1,
                                 start_date=now, end_date=now + timedelta(days=7)))
    # 무관 공고 (매칭 안 됨)
    db_session.add(models.Notice(bid_no="REC-NOPE", title="조경 식재 공사", basic_price=1,
                                 start_date=now, end_date=now + timedelta(days=7)))
    db_session.commit()

    with patch("app.tasks.recommendation_tasks.SessionLocal", lambda: _SessionWrapper(db_session)):
        r = send_recommendations()

    assert r["users_notified"] >= 1
    noti = (
        db_session.query(models.Notification)
        .filter(models.Notification.user_id == u.id,
                models.Notification.noti_type.like("REC_%"))
        .first()
    )
    assert noti is not None
    assert "REC-MATCH" in (noti.data_json or {}).get("bid_nos", [])


def test_recommendation_skips_user_without_profile(db_session):
    from app.tasks.recommendation_tasks import send_recommendations

    _user(db_session, "noprofile@test.com")  # licenses/location 없음
    now = datetime.now()
    db_session.add(models.Notice(bid_no="REC-X", title="전기 공사", basic_price=1,
                                 start_date=now, end_date=now + timedelta(days=7)))
    db_session.commit()

    with patch("app.tasks.recommendation_tasks.SessionLocal", lambda: _SessionWrapper(db_session)):
        r = send_recommendations()

    # 프로필 없는 사용자는 대상 제외 — 알림 없음
    noti = (
        db_session.query(models.Notification)
        .join(models.User, models.User.id == models.Notification.user_id)
        .filter(models.User.email == "noprofile@test.com")
        .first()
    )
    assert noti is None
