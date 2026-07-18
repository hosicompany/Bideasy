"""블로그(DB 글) Pydantic 스키마 — admin CRUD/발행 입출력."""
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, ConfigDict, field_validator


def _to_naive_utc(v: Optional[datetime]) -> Optional[datetime]:
    """publish_at 저장 기준(naive UTC)으로 정규화 — tz-aware 입력(예: +09:00)이 오면
    UTC 로 변환해 tzinfo 제거. 스케줄러(_naive_utc 비교)와 어긋나지 않게 일원화."""
    if v is not None and v.tzinfo is not None:
        v = v.astimezone(timezone.utc).replace(tzinfo=None)
    return v


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
    publish_at: Optional[datetime] = None  # 예약 발행 시각(UTC naive). 지정 시 스케줄러가 자동 발행

    _norm_publish_at = field_validator("publish_at")(_to_naive_utc)


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
    publish_at: Optional[datetime] = None  # 예약 시각 지정 / null 로 보류(유예 취소)

    _norm_publish_at = field_validator("publish_at")(_to_naive_utc)


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
    blocks_json: Optional[dict] = None          # 콘텐츠 엔진 구조화 정본 (Phase 1)
    channel_assets_json: Optional[dict] = None  # 채널 파생 캐시 (Phase 2)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
