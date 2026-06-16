"""블로그(DB 글) Pydantic 스키마 — admin CRUD/발행 입출력."""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class BlogPostCreate(BaseModel):
    title: str
    slug: Optional[str] = None       # 미지정 시 title 기반 자동 생성
    summary: str = ""
    category: str = ""
    tags: str = ""                   # 콤마 구분
    cover: str = ""
    hero: str = ""
    body_md: str = ""
    status: str = "draft"            # draft | published
    source: str = "admin"            # admin | auto
    date: Optional[str] = None       # YYYY-MM-DD (미지정·발행 시 오늘)


class BlogPostUpdate(BaseModel):
    title: Optional[str] = None
    slug: Optional[str] = None
    summary: Optional[str] = None
    category: Optional[str] = None
    tags: Optional[str] = None
    cover: Optional[str] = None
    hero: Optional[str] = None
    body_md: Optional[str] = None
    status: Optional[str] = None
    date: Optional[str] = None


class BlogPostOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    title: str
    summary: Optional[str] = ""
    category: Optional[str] = ""
    tags: Optional[str] = ""
    cover: Optional[str] = ""
    hero: Optional[str] = ""
    body_md: Optional[str] = ""
    body_html: Optional[str] = ""
    reading_time: int = 1
    status: str
    source: str
    date: Optional[str] = None
    publish_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
