"""관리자 블로그 CRUD/발행 — DB 기반 런타임 발행.

마크다운 파일(상록수)과 하이브리드. 여기서 만든 글은 **배포 없이 즉시 /blog 반영**.
Track B 자동 데이터스토리도 이 엔드포인트로 status=draft 초안을 꽂고, 사람이 1클릭 발행.
저장 시 services/blog.render() 로 파일과 동일한 렌더 파이프라인 사용.
"""
from __future__ import annotations

import re
import time
from datetime import date as date_cls

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.security import require_admin
from app.db import models
from app.db.session import get_db
from app.schemas.blog import BlogPostCreate, BlogPostOut, BlogPostUpdate
from app.services import blog as blog_svc

router = APIRouter()

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(text: str) -> str:
    return _SLUG_RE.sub("-", (text or "").lower()).strip("-")


def _ensure_unique_slug(slug: str, db: Session, exclude_id: int | None = None) -> None:
    """파일 글·DB 글 모두와 slug 충돌 금지."""
    if blog_svc.get_post(slug) is not None:  # db 미전달 → 파일 글만 검사
        raise HTTPException(409, f"slug '{slug}' 는 이미 파일 글에 있어요")
    q = db.query(models.BlogPost).filter(models.BlogPost.slug == slug)
    if exclude_id is not None:
        q = q.filter(models.BlogPost.id != exclude_id)
    if q.first() is not None:
        raise HTTPException(409, f"slug '{slug}' 중복")


def _get_or_404(post_id: int, db: Session) -> models.BlogPost:
    post = db.query(models.BlogPost).filter(models.BlogPost.id == post_id).first()
    if not post:
        raise HTTPException(404, "글을 찾을 수 없어요")
    return post


@router.get("/blog", response_model=list[BlogPostOut])
def list_blog_posts(db: Session = Depends(get_db), _admin=Depends(require_admin)):
    """관리자용 — 초안 포함 전체, 최신순."""
    return db.query(models.BlogPost).order_by(models.BlogPost.updated_at.desc()).all()


@router.get("/blog/topics")
def list_content_topics(db: Session = Depends(get_db), _admin=Depends(require_admin)):
    """콘텐츠 엔진 주제 큐 (Track K 시드 + 초안 존재 여부) — CONTENT_ENGINE Phase 1.

    주의: /blog/{post_id}(int) 보다 먼저 등록해야 'topics' 가 422 로 잡히지 않는다.
    """
    from app.services import content_engine
    return {"topics": content_engine.list_topics(db)}


@router.get("/blog/{post_id}", response_model=BlogPostOut)
def get_blog_post(post_id: int, db: Session = Depends(get_db), _admin=Depends(require_admin)):
    return _get_or_404(post_id, db)


@router.post("/blog", response_model=BlogPostOut, status_code=201)
def create_blog_post(payload: BlogPostCreate, db: Session = Depends(get_db), _admin=Depends(require_admin)):
    slug = (payload.slug or "").strip() or _slugify(payload.title) or f"post-{int(time.time())}"
    _ensure_unique_slug(slug, db)
    html, rt = blog_svc.render(payload.body_md)
    status = payload.status if payload.status in ("draft", "published") else "draft"
    date = payload.date or (date_cls.today().isoformat() if status == "published" else "")
    post = models.BlogPost(
        slug=slug,
        title=payload.title,
        summary=payload.summary,
        category=payload.category,
        tags=payload.tags,
        cover=payload.cover,
        hero=payload.hero,
        body_md=payload.body_md,
        body_html=html,
        reading_time=rt,
        status=status,
        source=payload.source if payload.source in ("admin", "auto") else "admin",
        date=date,
        publish_at=payload.publish_at,
    )
    db.add(post)
    db.commit()
    db.refresh(post)
    return post


@router.post("/blog/generate-from-topic/{topic_code}", response_model=BlogPostOut)
def generate_from_topic(topic_code: str, db: Session = Depends(get_db), _admin=Depends(require_admin)):
    """주제 코드로 구조화 정본 초안 생성 (검수 게이트 — publish_at 없이 draft).

    멱등: 같은 주제 초안이 있으면 그걸 반환. LLM 키 미설정이면 503(가짜 초안 금지).
    """
    from app.services import content_engine
    post, status = content_engine.create_draft_from_topic(db, topic_code.upper())
    if status == "unknown_topic":
        raise HTTPException(404, f"주제 코드 '{topic_code}' 를 찾을 수 없어요.")
    if status == "llm_unavailable":
        raise HTTPException(503, "AI 초안 생성을 지금 사용할 수 없어요 (LLM 키 미설정 또는 생성 실패).")
    return post


@router.post("/blog/generate-data-story", response_model=BlogPostOut)
def generate_data_story_now(db: Session = Depends(get_db), _admin=Depends(require_admin)):
    """지난주 개찰 데이터로 데이터스토리 초안 즉시 생성(수동·테스트용).

    Celery 주간 task(content.weekly_data_story)와 동일 로직. 이미 같은 주 초안이 있으면 그걸 반환.
    """
    from app.services import data_story
    post, status = data_story.create_weekly_draft(db)
    if status == "no_data":
        raise HTTPException(404, "지난주 개찰 데이터가 없어요 (opening_results 비어있음)")
    return post


@router.put("/blog/{post_id}", response_model=BlogPostOut)
def update_blog_post(post_id: int, payload: BlogPostUpdate, db: Session = Depends(get_db), _admin=Depends(require_admin)):
    post = _get_or_404(post_id, db)
    data = payload.model_dump(exclude_unset=True)
    if data.get("slug") and data["slug"] != post.slug:
        _ensure_unique_slug(data["slug"], db, exclude_id=post.id)
        post.slug = data["slug"]
    for f in ("title", "summary", "category", "tags", "cover", "hero", "date"):
        if data.get(f) is not None:
            setattr(post, f, data[f])
    if data.get("status") in ("draft", "published"):
        post.status = data["status"]
        if post.status == "published" and not post.date:
            post.date = date_cls.today().isoformat()
        # 발행 취소(→draft) 시 예약을 비워 스케줄러 재발행 방지(unpublish 와 일관).
        # 단, 같은 요청에 publish_at 이 명시되면 아래에서 그 값이 우선한다.
        if post.status == "draft" and "publish_at" not in data:
            post.publish_at = None
    # publish_at: 예약 시각 지정 또는 null 로 보류(유예 자동발행 취소). exclude_unset 이라
    # 키가 왔을 때만 반영 → 다른 필드 수정 시 예약이 의도치 않게 지워지지 않음.
    if "publish_at" in data:
        post.publish_at = data["publish_at"]
    if data.get("body_md") is not None:
        post.body_md = data["body_md"]
        post.body_html, post.reading_time = blog_svc.render(data["body_md"])
    db.commit()
    db.refresh(post)
    return post


@router.post("/blog/{post_id}/publish", response_model=BlogPostOut)
def publish_blog_post(post_id: int, db: Session = Depends(get_db), _admin=Depends(require_admin)):
    """초안 → 발행 (1클릭 승인). 발행 후 채널 자산 자동 파생(best-effort)."""
    post = _get_or_404(post_id, db)
    post.status = "published"
    post.date = post.date or date_cls.today().isoformat()
    db.commit()
    db.refresh(post)
    # Phase 2 — 검수된 정본에서만 파생. 실패해도 발행은 유지.
    from app.services import content_engine
    content_engine.ensure_channel_assets(db, post)
    db.refresh(post)
    return post


@router.post("/blog/{post_id}/derive-assets", response_model=BlogPostOut)
def derive_assets_now(post_id: int, force: bool = False, db: Session = Depends(get_db), _admin=Depends(require_admin)):
    """채널 자산 수동 (재)생성 — force=true 면 기존 자산 무시하고 재파생."""
    from app.services import content_engine
    post = _get_or_404(post_id, db)
    if not post.blocks_json:
        raise HTTPException(400, "구조화 블록(blocks_json)이 없는 글이에요 — 엔진 초안만 파생할 수 있어요.")
    if force:
        post.channel_assets_json = None
        db.commit()
    ok = content_engine.ensure_channel_assets(db, post)
    db.refresh(post)
    if not ok and not post.channel_assets_json:
        raise HTTPException(503, "채널 자산 생성을 지금 사용할 수 없어요 (LLM 키 미설정 또는 생성 실패).")
    return post


@router.post("/blog/{post_id}/unpublish", response_model=BlogPostOut)
def unpublish_blog_post(post_id: int, db: Session = Depends(get_db), _admin=Depends(require_admin)):
    """발행 → 초안 (게시 취소). 예약(publish_at)도 함께 해제해 스케줄러 재발행을 막는다."""
    post = _get_or_404(post_id, db)
    post.status = "draft"
    post.publish_at = None
    db.commit()
    db.refresh(post)
    return post


@router.delete("/blog/{post_id}", status_code=204)
def delete_blog_post(post_id: int, db: Session = Depends(get_db), _admin=Depends(require_admin)):
    post = _get_or_404(post_id, db)
    db.delete(post)
    db.commit()
    return None
