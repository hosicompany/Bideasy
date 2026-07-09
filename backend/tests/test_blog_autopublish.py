"""블로그 유예/예약 자동발행 — publish_at 스케줄러 + 데이터스토리 유예 부여.

- content.publish_scheduled: publish_at 도래한 draft 만 발행(미도래·무예약·기발행 제외)
- data_story.create_weekly_draft: 유예 publish_at 부여(config grace)
- unpublish 시 publish_at 해제(스케줄러 재발행 방지)
"""
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.db import models
from app.services import data_story
from app.tasks.content_tasks import publish_scheduled_posts


def _naive_utc():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class _SessionWrapper:
    """SessionLocal() → 테스트 세션 위임, close 는 no-op(fixture 가 처리)."""
    def __init__(self, real):
        self._real = real

    def __getattr__(self, name):
        if name == "close":
            return lambda: None
        return getattr(self._real, name)


def _patch_session(db_session):
    return patch("app.tasks.content_tasks.SessionLocal", lambda: _SessionWrapper(db_session))


def _mk_post(db, slug, status="draft", publish_at=None, date_str=""):
    p = models.BlogPost(
        slug=slug, title=f"글 {slug}", summary="", category="", tags="",
        body_md="본문", body_html="<p>본문</p>", reading_time=1,
        status=status, source="admin", date=date_str, publish_at=publish_at,
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


@pytest.fixture(autouse=True)
def no_llm(monkeypatch):
    monkeypatch.setattr(data_story, "_llm_narrative", lambda ctx: None)


class TestPublishScheduler:
    def test_publishes_due_draft(self, db_session):
        p = _mk_post(db_session, "due-1", publish_at=_naive_utc() - timedelta(hours=1))
        with _patch_session(db_session):
            res = publish_scheduled_posts()
        assert res["ok"] and "due-1" in res["published"]
        db_session.refresh(p)
        assert p.status == "published"
        assert p.date  # KST 오늘 세팅됨

    def test_skips_future_publish_at(self, db_session):
        p = _mk_post(db_session, "future-1", publish_at=_naive_utc() + timedelta(hours=5))
        with _patch_session(db_session):
            res = publish_scheduled_posts()
        assert "future-1" not in res["published"]
        db_session.refresh(p)
        assert p.status == "draft"

    def test_skips_draft_without_publish_at(self, db_session):
        p = _mk_post(db_session, "noschedule-1", publish_at=None)
        with _patch_session(db_session):
            res = publish_scheduled_posts()
        assert "noschedule-1" not in res["published"]
        db_session.refresh(p)
        assert p.status == "draft"

    def test_ignores_already_published(self, db_session):
        p = _mk_post(db_session, "pub-1", status="published",
                     publish_at=_naive_utc() - timedelta(hours=1), date_str="2026-01-01")
        with _patch_session(db_session):
            res = publish_scheduled_posts()
        assert "pub-1" not in res["published"]
        db_session.refresh(p)
        assert p.date == "2026-01-01"  # 기존 발행일 보존


class TestDataStoryGrace:
    def test_grace_sets_publish_at(self, db_session, monkeypatch):
        from app.core.config import settings
        monkeypatch.setattr(settings, "BLOG_AUTOPUBLISH_GRACE_HOURS", 48)
        ref = date(2025, 8, 18)
        mon, _ = data_story.last_completed_week(ref)
        od = datetime(mon.year, mon.month, mon.day) + timedelta(days=1, hours=10)
        db_session.add(models.OpeningResult(
            bid_no=f"OR-grace-{mon.isoformat()}", organization="A", region="서울",
            open_date=od, basic_price=1_000_000_000, winner_rate=88.0, participants_count=5,
        ))
        db_session.commit()
        post, status = data_story.create_weekly_draft(db_session, ref_date=ref)
        assert status == "created" and post.status == "draft"
        assert post.publish_at is not None
        delta = post.publish_at - _naive_utc()
        assert timedelta(hours=47) < delta <= timedelta(hours=48)

    def test_grace_zero_leaves_no_schedule(self, db_session, monkeypatch):
        from app.core.config import settings
        monkeypatch.setattr(settings, "BLOG_AUTOPUBLISH_GRACE_HOURS", 0)
        ref = date(2025, 8, 25)
        mon, _ = data_story.last_completed_week(ref)
        od = datetime(mon.year, mon.month, mon.day) + timedelta(days=1, hours=10)
        db_session.add(models.OpeningResult(
            bid_no=f"OR-nograce-{mon.isoformat()}", organization="A", region="서울",
            open_date=od, basic_price=1_000_000_000, winner_rate=88.0, participants_count=5,
        ))
        db_session.commit()
        post, status = data_story.create_weekly_draft(db_session, ref_date=ref)
        assert status == "created"
        assert post.publish_at is None  # 킬스위치: 유예 미부여


class TestUnpublishClearsSchedule:
    def test_unpublish_clears_publish_at(self, admin_client, db_session):
        p = _mk_post(db_session, "unpub-1", status="published",
                     publish_at=_naive_utc() - timedelta(hours=1), date_str="2026-01-01")
        r = admin_client.post(f"/api/v1/admin/blog/{p.id}/unpublish")
        assert r.status_code == 200
        db_session.refresh(p)
        assert p.status == "draft"
        assert p.publish_at is None  # 재발행 방지

    def test_update_to_draft_clears_publish_at(self, admin_client, db_session):
        """PUT 으로 발행 취소(→draft) 시에도 예약 해제 → 스케줄러 재발행 안 함."""
        p = _mk_post(db_session, "upd-draft-1", status="published",
                     publish_at=_naive_utc() - timedelta(hours=1), date_str="2026-01-01")
        r = admin_client.put(f"/api/v1/admin/blog/{p.id}", json={"status": "draft", "body_md": "수정"})
        assert r.status_code == 200
        db_session.refresh(p)
        assert p.status == "draft" and p.publish_at is None
        with _patch_session(db_session):
            res = publish_scheduled_posts()
        assert "upd-draft-1" not in res["published"]  # 재발행 안 됨

    def test_update_draft_explicit_publish_at_wins(self, admin_client, db_session):
        """→draft 전이라도 같은 요청에 publish_at 명시되면 그 값이 우선(재예약)."""
        p = _mk_post(db_session, "upd-draft-2", status="published", date_str="2026-01-01")
        future = (_naive_utc() + timedelta(days=3)).isoformat()
        r = admin_client.put(f"/api/v1/admin/blog/{p.id}", json={"status": "draft", "publish_at": future})
        assert r.status_code == 200
        db_session.refresh(p)
        assert p.publish_at is not None


class TestTzAwareNormalization:
    def test_create_schema_normalizes_tz_aware(self):
        from app.schemas.blog import BlogPostCreate
        # KST(+09:00) 18:00 → naive UTC 09:00
        m = BlogPostCreate(title="t", publish_at="2026-07-09T18:00:00+09:00")
        assert m.publish_at.tzinfo is None
        assert m.publish_at == datetime(2026, 7, 9, 9, 0, 0)

    def test_update_schema_normalizes_tz_aware(self):
        from app.schemas.blog import BlogPostUpdate
        m = BlogPostUpdate(publish_at="2026-07-09T18:00:00+09:00")
        assert m.publish_at.tzinfo is None and m.publish_at.hour == 9
