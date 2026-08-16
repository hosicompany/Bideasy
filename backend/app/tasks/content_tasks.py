"""Track B 데이터 스토리 — 주간 자동 초안 생성 + 예약/유예 자동 발행 Celery 태스크.

- content.weekly_data_story (월 08:00 KST): 지난주 개찰 데이터로 초안 생성. 유예
  publish_at 이 부여돼(config BLOG_AUTOPUBLISH_GRACE_HOURS) 그 시간 뒤 자동 발행됨.
- content.weekly_knowledge_draft (수 07:00 KST): K-큐 자동 초안. 검사가 생략되지 않은
  PASS/WARN만 유예 publish_at 부여(config BLOG_KNOWLEDGE_GRACE_HOURS, 0=수동 승인 유지).
- content.publish_scheduled (매시): publish_at 이 도래한 draft 를 발행. 데이터스토리
  유예 자동발행·K 유예 자동발행·상록수 예약 드립을 한 스케줄러로 처리. 발행 직전
  히어로 파일 존재를 확인해 미배치면 hero 를 비운다(깨진 og:image 방지).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import requests

from app.core.celery_app import celery_app
from app.core.config import settings
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


def _hero_available(hero: str) -> bool:
    """발행 직전 히어로 파일 존재 확인 (§5.1 — 깨진 이미지가 발행되는 사고 방지).

    자동 초안의 hero 는 이미지 배치 전 경로일 수 있다(파일은 사람이 생성·배포).
    404 인 채 발행되면 og:image 가 깨진 링크로 나간다. 확인 자체가 실패해도
    False 로 본다 — 공개 페이지에 확인하지 못한 이미지 URL을 내보내는 것보다
    이미지 없이 발행하는 쪽이 안전하고, hero 는 관리자 화면에서 복구 가능하다.
    """
    from app.services import indexnow

    try:
        r = requests.head(f"{indexnow.SITE_URL}{hero}", timeout=3, allow_redirects=True)
        return r.status_code == 200
    except Exception:
        logger.warning("[content.publish_scheduled] hero 확인 실패: %s", hero, exc_info=True)
        return False


def _knowledge_review_route(review: dict | None) -> tuple[bool, str]:
    """K-트랙 검수 결과가 자동발행 가능한지 판정한다.

    `verdict=WARN`만 보면 안 된다. LLM 심판 호출 실패도 WARN이지만 이때 check에
    `skipped=True`가 남는다. 검사를 못 한 상태를 정상 advisory와 섞으면 사실상
    무검수 자동발행이므로, skipped 검사가 하나라도 있으면 사람 경로로 보낸다.
    """
    from app.services import content_review

    if not isinstance(review, dict) or not review:
        return False, "review_missing"
    verdict = review.get("verdict")
    if verdict not in (content_review.PASS, content_review.WARN, content_review.FAIL):
        return False, "review_unknown"

    checks = review.get("checks")
    if not isinstance(checks, list) or not checks or not all(isinstance(c, dict) for c in checks):
        return False, "review_incomplete"

    codes = [check.get("code") for check in checks]
    if any(not isinstance(code, str) or not code for code in codes):
        return False, "review_incomplete"
    if len(codes) != len(set(codes)):
        return False, "review_incomplete"
    if not content_review.AUTO_PUBLISH_REQUIRED_CHECK_CODES.issubset(codes):
        return False, "review_incomplete"
    if any(check.get("skipped") for check in checks):
        return False, "review_incomplete"

    levels = [check.get("level") for check in checks]
    if any(not isinstance(level, str) or level not in content_review.REVIEW_LEVEL_ORDER for level in levels):
        return False, "review_incomplete"
    computed_verdict = max(levels, key=lambda level: content_review.REVIEW_LEVEL_ORDER[level])
    if computed_verdict != verdict:
        return False, "review_inconsistent"
    if verdict == content_review.FAIL:
        return False, "review_failed"
    return True, verdict.lower()


def _is_knowledge_auto(post: models.BlogPost) -> bool:
    """검수 판정 연동 대상인 자동 생성 K-트랙 글인지 식별한다."""
    return post.source == "auto" and post.category == "입찰상식"


@celery_app.task(name="content.weekly_data_story")
def generate_weekly_data_story() -> dict:
    """매주 월 08:00 KST — 지난주 데이터스토리 초안 생성 + 관리자 알림."""
    db = SessionLocal()
    try:
        post, status = data_story.create_weekly_draft(db)
        if status == "no_data":
            logger.info("[content.weekly_data_story] 지난주 개찰 데이터 없음 — 건너뜀")
            return {"ok": True, "skipped": "no_data"}
        if status == "thin_data":
            # 조용한 스킵 금지 — 블로그가 소리 없이 멈추는 것을 관리자가 알아야 한다.
            # (임계 자체는 §9.2 스팸정책 방어라 자동 강행하지 않는다)
            admins = db.query(models.User).filter(models.User.is_admin == True).all()  # noqa: E712
            for a in admins:
                db.add(models.Notification(
                    user_id=a.id,
                    title="🪶 데이터스토리 건너뜀 — 데이터가 얇아요",
                    body=(
                        f"지난주 개찰 건수가 최소 임계({data_story.min_weekly_records()}건) 미만이라 "
                        "이번 주 글을 만들지 않았어요. 크롤이 정상인지 확인해보세요."
                    ),
                    noti_type="BLOG_THIN_WEEK_SKIPPED",
                    data_json={"threshold": data_story.min_weekly_records()},
                    is_read=0,
                ))
            db.commit()
            logger.warning("[content.weekly_data_story] 얇은 주 — 건너뜀 + 관리자 경보")
            return {"ok": True, "skipped": "thin_data"}
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

    검수 게이트 연동(2026-08-10): FAIL(blocking 실패)·검사 생략은 draft 로 남겨
    사람을 부르고, 완결된 PASS/WARN(advisory 뿐)은 유예 publish_at 을 부여한다.
    BLOG_KNOWLEDGE_GRACE_HOURS=0 이면 종전대로 전부 수동 승인(킬스위치).
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
            # Phase 2 — 판정 연동 유예 자동발행 (docs/CONTENT_ENGINE.md §10.3).
            # FAIL(blocking 검사 실패)·검사 생략은 사람을 부르고, 완결된
            # PASS/WARN(advisory 뿐)은 유예 뒤 자동 발행한다. review_json 이 없으면
            # 판정을 모르는 상태이므로 예약하지 않는다 — 모르면 사람이 본다.
            grace = settings.BLOG_KNOWLEDGE_GRACE_HOURS
            verdict = (post.review_json or {}).get("verdict")
            eligible, route = _knowledge_review_route(post.review_json)
            scheduled = None
            if grace > 0 and eligible:
                post.publish_at = _naive_utc() + timedelta(hours=grace)
                scheduled = post.publish_at
            if scheduled is not None:
                title = "⏱️ 입찰상식 초안 자동 발행 예약됨"
                body = (
                    f"[{topic['code']}] {post.title} — 검수 {verdict}. {grace}시간 뒤 자동 발행돼요. "
                    "그 전에 이미지를 배치하거나, 보류하려면 /admin-blog 에서 예약을 비우세요."
                )
            elif verdict == "FAIL":
                title = "🛑 입찰상식 초안 검수 FAIL — 확인 필요"
                body = (
                    f"[{topic['code']}] {post.title} — 검수 게이트 FAIL. "
                    "/admin-blog 에서 원인을 확인·정정하세요 (자동 발행하지 않습니다)."
                )
            elif not eligible:
                title = "⚠️ 입찰상식 자동 검수 미완료 — 확인 필요"
                body = (
                    f"[{topic['code']}] {post.title} — 검수 결과가 완결되지 않아 자동 발행을 예약하지 않았어요. "
                    "/admin-blog 에서 검수 결과를 확인하세요."
                )
            else:
                title = "✍️ 입찰상식 초안 생성됨"
                body = f"[{topic['code']}] {post.title} — /admin-blog 에서 검수 후 발행/예약하세요."
            for a in admins:
                db.add(models.Notification(
                    user_id=a.id,
                    title=title,
                    body=body,
                    noti_type="BLOG_DRAFT_READY",
                    data_json={"slug": post.slug, "post_id": post.id, "verdict": verdict,
                               "review_route": route,
                               "publish_at": scheduled.isoformat() if scheduled else None},
                    is_read=0,
                ))
            # 예약과 사전 알림은 한 트랜잭션으로 고정한다. 둘 중 하나만 남으면
            # 관리자가 모르는 자동발행이 생기거나, 존재하지 않는 예약을 안내하게 된다.
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
            # task_acks_late 재전달·수동 중복 실행이 겹쳐도 같은 글을 두 워커가
            # 동시에 발행/알림/파생하지 않도록 Postgres에서 행을 선점한다.
            # SQLite 테스트에서는 dialect가 FOR UPDATE를 생략한다.
            .with_for_update(skip_locked=True)
            .all()
        )
        if not due:
            return {"ok": True, "published": [], "no_hero": [], "blocked": []}

        today = _kst_today_iso()
        published = []
        published_posts = []
        no_hero = []
        blocked = []
        for p in due:
            # 예약 뒤 본문/판정이 바뀌었거나, 과거 구현이 skipped 검사를 예약한 경우를
            # 발행 직전에 한 번 더 막는다. 자동 K-트랙에만 적용해 수동 예약·데이터스토리
            # 동작은 바꾸지 않는다.
            if _is_knowledge_auto(p):
                eligible, route = _knowledge_review_route(p.review_json)
                if not eligible:
                    p.publish_at = None
                    blocked.append({"slug": p.slug, "reason": route})
                    continue
            # 미배치 히어로는 비우고 발행 — 텍스트는 나가고 깨진 og:image 는 안 나간다.
            # 이미지를 나중에 배치하면 admin PUT 으로 hero 를 되살릴 수 있다.
            if p.hero and p.hero.startswith("/assets/blog/") and not _hero_available(p.hero):
                no_hero.append(p.slug)
                p.hero = ""
            p.status = "published"
            if not p.date:
                p.date = today
            published.append(p.slug)
            published_posts.append(p)

        # 관리자 알림(사후 인지 — 필요 시 unpublish 가능, 런타임이라 즉시 가역)
        admins = db.query(models.User).filter(models.User.is_admin == True).all()  # noqa: E712
        if published:
            preview = ", ".join(published[:5]) + (" 외" if len(published) > 5 else "")
            body = f"{len(published)}건이 발행됐어요: {preview}"
            if no_hero:
                body += f" (히어로 미배치로 이미지 없이 발행: {', '.join(no_hero)})"
            for a in admins:
                db.add(models.Notification(
                    user_id=a.id,
                    title="📢 예약 글 자동 발행됨",
                    body=body,
                    noti_type="BLOG_AUTO_PUBLISHED",
                    data_json={"slugs": published, "no_hero": no_hero},
                    is_read=0,
                ))
        if blocked:
            blocked_slugs = ", ".join(item["slug"] for item in blocked[:5])
            for a in admins:
                db.add(models.Notification(
                    user_id=a.id,
                    title="🛑 입찰상식 자동 발행 차단됨",
                    body=f"검수 결과가 없거나 미완료여서 예약을 해제했어요: {blocked_slugs}",
                    noti_type="BLOG_AUTO_PUBLISH_BLOCKED",
                    data_json={"posts": blocked},
                    is_read=0,
                ))
        db.commit()
        if published:
            logger.info(
                f"[content.publish_scheduled] 자동 발행 {len(published)}건: {published}"
                + (f" (히어로 미배치 {no_hero})" if no_hero else "")
            )
        if blocked:
            logger.warning("[content.publish_scheduled] 검수 불완전 예약 해제: %s", blocked)

        # Phase 2: 발행된 글의 채널 자산 자동 파생 (best-effort — 발행은 이미 완료)
        try:
            from app.services import content_engine
            derived = [p.slug for p in published_posts if content_engine.ensure_channel_assets(db, p)]
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

        # 색인 통보(best-effort) — 발행은 이미 커밋됐으므로 실패해도 되돌리지 않는다.
        if published:
            from app.services import indexnow
            indexnow.submit(
                indexnow.blog_urls(published) + [f"{indexnow.SITE_URL}/blog"],
                reason="publish_scheduled",
            )

        return {"ok": True, "published": published, "no_hero": no_hero, "blocked": blocked}
    except Exception as e:
        db.rollback()
        logger.error(f"[content.publish_scheduled] error: {e}", exc_info=True)
        return {"ok": False, "error": str(e)}
    finally:
        db.close()
