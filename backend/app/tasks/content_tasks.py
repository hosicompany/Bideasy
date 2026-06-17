"""Track B 데이터 스토리 — 주간 자동 초안 생성 Celery 태스크.

매주 월요일 08:00 KST: 지난주 개찰 데이터로 글 초안(status=draft, source=auto)을 만들고
관리자에게 '검토 후 발행' 알림. 사람이 /admin-blog 에서 1클릭 발행.
"""
from __future__ import annotations

from app.core.celery_app import celery_app
from app.core.logging import get_logger
from app.db import models
from app.db.session import SessionLocal
from app.services import data_story

logger = get_logger(__name__)


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
