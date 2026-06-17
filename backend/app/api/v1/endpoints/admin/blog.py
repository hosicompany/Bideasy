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
    )
    db.add(post)
    db.commit()
    db.refresh(post)
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
    if data.get("body_md") is not None:
        post.body_md = data["body_md"]
        post.body_html, post.reading_time = blog_svc.render(data["body_md"])
    db.commit()
    db.refresh(post)
    return post


@router.post("/blog/{post_id}/publish", response_model=BlogPostOut)
def publish_blog_post(post_id: int, db: Session = Depends(get_db), _admin=Depends(require_admin)):
    """초안 → 발행 (1클릭 승인)."""
    post = _get_or_404(post_id, db)
    post.status = "published"
    post.date = post.date or date_cls.today().isoformat()
    db.commit()
    db.refresh(post)
    return post


@router.post("/blog/{post_id}/unpublish", response_model=BlogPostOut)
def unpublish_blog_post(post_id: int, db: Session = Depends(get_db), _admin=Depends(require_admin)):
    """발행 → 초안 (게시 취소)."""
    post = _get_or_404(post_id, db)
    post.status = "draft"
    db.commit()
    db.refresh(post)
    return post


@router.delete("/blog/{post_id}", status_code=204)
def delete_blog_post(post_id: int, db: Session = Depends(get_db), _admin=Depends(require_admin)):
    post = _get_or_404(post_id, db)
    db.delete(post)
    db.commit()
    return None
