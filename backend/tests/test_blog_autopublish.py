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
        # 관심사는 유예(publish_at) — 얇은 주 게이트(§9.2)는 allow_thin 으로 비껴간다
        post, status = data_story.create_weekly_draft(db_session, ref_date=ref, allow_thin=True)
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
        # 관심사는 유예(publish_at) — 얇은 주 게이트(§9.2)는 allow_thin 으로 비껴간다
        post, status = data_story.create_weekly_draft(db_session, ref_date=ref, allow_thin=True)
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

    def test_editing_auto_post_invalidates_review_and_schedule(self, admin_client, db_session):
        """유예 중 본문을 고치면 옛 판정으로 자동발행하지 않는다."""
        p = _mk_post(
            db_session,
            "auto-edit-invalidates-review",
            publish_at=_naive_utc() + timedelta(days=2),
        )
        p.source = "auto"
        p.category = "입찰상식"
        p.review_json = {"verdict": "WARN", "checks": []}
        p.channel_assets_json = {"stale": True}
        db_session.commit()

        r = admin_client.put(
            f"/api/v1/admin/blog/{p.id}",
            json={"body_md": "수정한 본문"},
        )
        assert r.status_code == 200
        db_session.refresh(p)
        assert p.publish_at is None
        assert p.review_json is None
        assert p.channel_assets_json is None


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


class TestKnowledgeGrace:
    """수요일 K-큐 자동 초안 — 검수 판정 연동 유예 자동발행 (Phase 2, §10.3).

    FAIL(blocking)만 사람을 부르고 PASS/WARN(advisory 뿐)은 유예 뒤 자동 발행.
    review_json 이 없으면(검수 실패) 판정을 모르므로 예약하지 않는다.
    """

    def _run(self, db_session, monkeypatch, verdict, grace=48, *, skipped=False):
        from app.core.config import settings
        from app.tasks.content_tasks import weekly_knowledge_draft

        monkeypatch.setattr(settings, "BLOG_KNOWLEDGE_GRACE_HOURS", grace)
        review_kind = "skipped" if skipped else "complete"
        slug = f"k-grace-{verdict or 'none'}-{grace}-{review_kind}"
        post = _mk_post(db_session, slug)
        post.review_json = (
            {"verdict": verdict, "checks": [
                {"code": "llm_judge", "level": verdict, "skipped": True}
            ] if skipped else []}
            if verdict else None
        )
        db_session.commit()
        topic = {"code": "K99", "title": "테스트 주제", "angle": "a", "keyword": "k", "priority": "P1"}
        with _patch_session(db_session), \
                patch("app.services.content_engine.next_unconsumed_topic", lambda db: topic), \
                patch("app.services.content_engine.create_draft_from_topic",
                      lambda db, code: (post, "created")), \
                patch("app.services.content_engine.remaining_topics", lambda db: 10):
            res = weekly_knowledge_draft()
        db_session.refresh(post)
        return res, post

    def test_warn_gets_grace_schedule(self, db_session, monkeypatch):
        res, post = self._run(db_session, monkeypatch, "WARN", grace=48)
        assert res["ok"]
        assert post.publish_at is not None
        delta = post.publish_at - _naive_utc()
        assert timedelta(hours=47) < delta <= timedelta(hours=48)

    def test_pass_gets_grace_schedule(self, db_session, monkeypatch):
        _, post = self._run(db_session, monkeypatch, "PASS", grace=24)
        assert post.publish_at is not None

    def test_fail_stays_manual(self, db_session, monkeypatch):
        _, post = self._run(db_session, monkeypatch, "FAIL", grace=48)
        assert post.publish_at is None  # blocking 실패 — 사람 호출

    def test_no_review_stays_manual(self, db_session, monkeypatch):
        _, post = self._run(db_session, monkeypatch, None, grace=48)
        assert post.publish_at is None  # 판정 미상 — 모르면 사람이 본다

    def test_killswitch_zero_stays_manual(self, db_session, monkeypatch):
        _, post = self._run(db_session, monkeypatch, "WARN", grace=0)
        assert post.publish_at is None  # 킬스위치: 종전 수동 승인 유지

    def test_skipped_review_stays_manual(self, db_session, monkeypatch):
        """LLM 심판 실패 WARN은 정상 advisory가 아니다 — 무검수 자동발행 방지."""
        _, post = self._run(db_session, monkeypatch, "WARN", grace=48, skipped=True)
        assert post.publish_at is None


class TestKnowledgePublishRecheck:
    """유예 뒤 실제 발행 시점에도 K-트랙 검수 상태를 다시 확인한다."""

    @staticmethod
    def _post(db, slug, review):
        p = _mk_post(db, slug, publish_at=_naive_utc() - timedelta(hours=1))
        p.source = "auto"
        p.category = "입찰상식"
        p.review_json = review
        db.commit()
        return p

    def test_missing_review_unschedules_instead_of_publishing(self, db_session):
        p = self._post(db_session, "k-review-missing", None)
        with _patch_session(db_session):
            res = publish_scheduled_posts()
        db_session.refresh(p)
        assert p.status == "draft" and p.publish_at is None
        assert res["blocked"] == [{"slug": p.slug, "reason": "review_missing"}]

    def test_skipped_review_unschedules_instead_of_publishing(self, db_session):
        review = {
            "verdict": "WARN",
            "checks": [{"code": "llm_judge", "level": "WARN", "skipped": True}],
        }
        p = self._post(db_session, "k-review-skipped", review)
        with _patch_session(db_session):
            res = publish_scheduled_posts()
        db_session.refresh(p)
        assert p.status == "draft" and p.publish_at is None
        assert res["blocked"][0]["reason"] == "review_incomplete"

    def test_complete_warn_still_publishes(self, db_session):
        review = {
            "verdict": "WARN",
            "checks": [{"code": "structure", "level": "WARN"}],
        }
        p = self._post(db_session, "k-review-complete", review)
        with _patch_session(db_session):
            res = publish_scheduled_posts()
        db_session.refresh(p)
        assert p.status == "published"
        assert p.slug in res["published"] and res["blocked"] == []


class TestHeroGuardOnPublish:
    """발행 직전 히어로 파일 확인 — 미배치면 hero 를 비워 깨진 og:image 방지(§5.1)."""

    def _mk_hero_post(self, db, slug):
        p = _mk_post(db, slug, publish_at=_naive_utc() - timedelta(hours=1))
        p.hero = f"/assets/blog/{slug}/hero.png"
        db.commit()
        db.refresh(p)
        return p

    @staticmethod
    def _resp(code):
        return type("R", (), {"status_code": code})()

    def test_missing_hero_cleared_but_published(self, db_session):
        p = self._mk_hero_post(db_session, "hero-404")
        with _patch_session(db_session), \
                patch("app.tasks.content_tasks.requests.head", return_value=self._resp(404)):
            res = publish_scheduled_posts()
        db_session.refresh(p)
        assert p.status == "published"
        assert p.hero == "" and "hero-404" in res["no_hero"]

    def test_existing_hero_kept(self, db_session):
        p = self._mk_hero_post(db_session, "hero-200")
        with _patch_session(db_session), \
                patch("app.tasks.content_tasks.requests.head", return_value=self._resp(200)):
            res = publish_scheduled_posts()
        db_session.refresh(p)
        assert p.status == "published"
        assert p.hero == "/assets/blog/hero-200/hero.png" and res["no_hero"] == []

    def test_check_failure_clears_hero(self, db_session):
        """확인 자체가 실패해도 깨질 수 있는 공개 URL보다 이미지 없는 발행이 안전하다."""
        p = self._mk_hero_post(db_session, "hero-err")
        with _patch_session(db_session), \
                patch("app.tasks.content_tasks.requests.head", side_effect=OSError("boom")):
            res = publish_scheduled_posts()
        db_session.refresh(p)
        assert p.status == "published"
        assert p.hero == "" and res["no_hero"] == ["hero-err"]
