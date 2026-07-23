"""Track B 데이터 스토리 — 주간 자동 초안 생성 + 예약/유예 자동 발행 Celery 태스크.

- content.weekly_data_story (월 08:00 KST): 지난주 개찰 데이터로 초안 생성. 유예
  publish_at 이 부여돼(config BLOG_AUTOPUBLISH_GRACE_HOURS) 그 시간 뒤 자동 발행됨.
- content.publish_scheduled (매시): publish_at 이 도래한 draft 를 발행. 데이터스토리
  유예 자동발행과 상록수 예약 드립(admin 이 publish_at 지정)을 한 스케줄러로 처리.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.core.celery_app import celery_app
from app.core.logging import get_logger
from app.db import models
from app.db.session import SessionLocal
from app.services import data_story

logger = get_logger(__name__)


def _naive_utc() -> datetime:
    """naive UTC — publish_at 저장/비교를 동일 기준으로(타임존 혼선 방지)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _kst_today_iso() -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=9)).date().isoformat()


@celery_app.task(name="content.weekly_data_story")
def generate_weekly_data_story() -> dict:
    """매주 월 08:00 KST — 지난주 데이터스토리 초안 생성 + 관리자 알림."""
    db = SessionLocal()
    try:
        post, status = data_story.create_weekly_draft(db)
        if status == "no_data":
            logger.info("[content.weekly_data_story] 지난주 개찰 데이터 없음 — 건너뜀")
            return {"ok": True, "skipped": "no_data"}
        if status == "exists":
            logger.info(f"[content.weekly_data_story] 이미 존재: {post.slug if post else '?'}")
            return {"ok": True, "skipped": "exists", "slug": post.slug if post else None}

        # 관리자 알림 (검토 후 발행 유도)
        admins = db.query(models.User).filter(models.User.is_admin == True).all()  # noqa: E712
        for a in admins:
            db.add(models.Notification(
                user_id=a.id,
                title="✍️ 데이터스토리 초안 생성됨",
                body=f"{post.title} — /admin-blog 에서 검토 후 발행하세요.",
                noti_type="BLOG_DRAFT_READY",
                data_json={"slug": post.slug, "post_id": post.id},
                is_read=0,
            ))
        db.commit()
        logger.info(f"[content.weekly_data_story] 초안 생성: {post.slug} (id={post.id})")
        return {"ok": True, "slug": post.slug, "post_id": post.id}
    except Exception as e:
        db.rollback()
        logger.error(f"[content.weekly_data_story] error: {e}", exc_info=True)
        return {"ok": False, "error": str(e)}
    finally:
        db.close()


@celery_app.task(name="content.weekly_knowledge_draft")
def weekly_knowledge_draft() -> dict:
    """수요일 아침 — K-큐(입찰상식) 미소비 최우선 주제 1개 자동 초안 (Phase 2 주간 루프).

    검수 게이트 유지: publish_at 없이 draft 만 생성, 관리자 알림 → 사람이 검수·발행/예약.
    멱등: 미소비 주제 없으면 no-op. LLM 키 미설정이면 알림으로 정직 보고(가짜 초안 금지).
    """
    db = SessionLocal()
    try:
        from app.services import content_engine

        topic = content_engine.next_unconsumed_topic(db)
        if topic is None:
            # 조용한 소진 금지 — 블로그가 소리 없이 멈추는 것을 막는다 (지속가능성 경보)
            admins = db.query(models.User).filter(models.User.is_admin == True).all()  # noqa: E712
            for a in admins:
                db.add(models.Notification(
                    user_id=a.id,
                    title="🪫 입찰상식 주제 큐 소진",
                    body="K-큐가 전부 소비됐어요. 이번 주 자동 초안이 없습니다 — 세션에서 '주제 큐 보충'을 요청해 신규 시드를 추가하세요.",
                    noti_type="TOPIC_QUEUE_EMPTY",
                    data_json={"remaining": 0},
                    is_read=0,
                ))
            db.commit()
            logger.warning("[content.weekly_knowledge_draft] K-큐 소진 — 관리자 경보 발송")
            return {"ok": True, "status": "queue_empty"}

        post, status = content_engine.create_draft_from_topic(db, topic["code"])
        admins = db.query(models.User).filter(models.User.is_admin == True).all()  # noqa: E712
        if status == "created":
            for a in admins:
                db.add(models.Notification(
                    user_id=a.id,
                    title="✍️ 입찰상식 초안 생성됨",
                    body=f"[{topic['code']}] {post.title} — /admin-blog 에서 검수 후 발행/예약하세요.",
                    noti_type="BLOG_DRAFT_READY",
                    data_json={"slug": post.slug, "post_id": post.id},
                    is_read=0,
                ))
            db.commit()
        elif status == "llm_unavailable":
            for a in admins:
                db.add(models.Notification(
                    user_id=a.id,
                    title="⚠️ 입찰상식 초안 생성 실패",
                    body=f"[{topic['code']}] LLM 키 미설정 또는 생성 실패 — 이번 주 초안이 만들어지지 않았어요.",
                    noti_type="BLOG_DRAFT_FAILED",
                    data_json={"topic_code": topic["code"]},
                    is_read=0,
                ))
            db.commit()
        # 소진 임박 경보 — 잔여 ≤ 워터마크(약 1개월분)면 보충을 미리 요청
        remaining = content_engine.remaining_topics(db)
        if remaining <= content_engine.LOW_QUEUE_WATERMARK:
            for a in admins:
                db.add(models.Notification(
                    user_id=a.id,
                    title=f"🔋 주제 큐 잔여 {remaining}개 — 보충 필요",
                    body="약 한 달 안에 소진돼요. /admin/blog/topics/propose 로 AI 후보를 받아 검토하거나, 세션에서 '주제 큐 보충'을 요청하세요.",
                    noti_type="TOPIC_QUEUE_LOW",
                    data_json={"remaining": remaining},
                    is_read=0,
                ))
            db.commit()

        logger.info(f"[content.weekly_knowledge_draft] {topic['code']} → {status} (잔여 {remaining})")
        return {"ok": status == "created", "status": status, "topic": topic["code"], "remaining": remaining}
    except Exception as e:
        db.rollback()
        logger.error(f"[content.weekly_knowledge_draft] error: {e}", exc_info=True)
        return {"ok": False, "error": str(e)}
    finally:
        db.close()


@celery_app.task(name="content.publish_scheduled")
def publish_scheduled_posts() -> dict:
    """publish_at 이 도래한 draft 를 자동 발행(매시).

    대상: status=draft & publish_at 설정됨 & publish_at <= now. 발행 시 date=KST 오늘.
    - 데이터스토리 유예 자동발행(생성 시 publish_at=now+grace)
    - 상록수 예약 드립(admin 이 publish_at 지정)
    사람이 그 전에 발행/삭제/보류(publish_at=null)하면 대상에서 빠진다.
    """
    db = SessionLocal()
    try:
        now = _naive_utc()
        # 배치 상한: grace 변경·스케줄러 장기 정지 후 backlog 가 쌓여도 한 회차에 폭발
        # 발행하지 않도록 제한(다음 :05 회차에 이어서 처리). 오래 예약된 것부터.
        due = (
            db.query(models.BlogPost)
            .filter(
                models.BlogPost.status == "draft",
                models.BlogPost.publish_at.isnot(None),
                models.BlogPost.publish_at <= now,
            )
            .order_by(models.BlogPost.publish_at.asc())
            .limit(50)
            .all()
        )
        if not due:
            return {"ok": True, "published": []}

        today = _kst_today_iso()
        published = []
        for p in due:
            p.status = "published"
            if not p.date:
                p.date = today
            published.append(p.slug)

        # 관리자 알림(사후 인지 — 필요 시 unpublish 가능, 런타임이라 즉시 가역)
        admins = db.query(models.User).filter(models.User.is_admin == True).all()  # noqa: E712
        preview = ", ".join(published[:5]) + (" 외" if len(published) > 5 else "")
        for a in admins:
            db.add(models.Notification(
                user_id=a.id,
                title="📢 예약 글 자동 발행됨",
                body=f"{len(published)}건이 발행됐어요: {preview}",
                noti_type="BLOG_AUTO_PUBLISHED",
                data_json={"slugs": published},
                is_read=0,
            ))
        db.commit()
        logger.info(f"[content.publish_scheduled] 자동 발행 {len(published)}건: {published}")

        # Phase 2: 발행된 글의 채널 자산 자동 파생 (best-effort — 발행은 이미 완료)
        try:
            from app.services import content_engine
            derived = [p.slug for p in due if content_engine.ensure_channel_assets(db, p)]
            if derived:
                for a in admins:
                    db.add(models.Notification(
                        user_id=a.id,
                        title="🎴 채널 자산 준비됨",
                        body=f"{len(derived)}건의 카드/릴스/유튜브 카피가 생성됐어요 — /admin-blog 에서 복사하세요.",
                        noti_type="CHANNEL_ASSETS_READY",
                        data_json={"slugs": derived},
                        is_read=0,
                    ))
                db.commit()
        except Exception:
            logger.exception("[content.publish_scheduled] channel assets derivation skipped")

        return {"ok": True, "published": published}
    except Exception as e:
        db.rollback()
        logger.error(f"[content.publish_scheduled] error: {e}", exc_info=True)
        return {"ok": False, "error": str(e)}
    finally:
        db.close()
