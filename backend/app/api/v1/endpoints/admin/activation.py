"""
관리자 활성화(activation) 계측 통계 API
========================================
신규 가입자의 활성화 2단계 — ① 프로필 완성(면허·소재지 입력) ② 첫 안전 판정(AI 분석/계산
요청) — 을 서버 타임스탬프(User.created_at/profile_completed_at/first_activation_at)로
집계한다.

Endpoints:
- GET /admin/stats/activation — 전체/계측대상 가입자 수, 프로필완성·활성화 비율, 일별 시리즈
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.security import require_admin
from app.db import models
from app.db.session import get_db

router = APIRouter()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _pct(numerator: int, denominator: int) -> float:
    """분모가 0 이면 0.0 — 계측 이전 가입자만 있는 경우(with_created_at=0) 등."""
    return round(numerator / denominator * 100, 1) if denominator else 0.0


@router.get("/stats/activation")
def activation_stats(
    days: int = Query(30, ge=7, le=365, description="일별 시리즈 기간"),
    db: Session = Depends(get_db),
    _admin=Depends(require_admin),
):
    """활성화 퍼널 집계.

    분모(퍼센트 계산)는 반드시 `with_created_at`(계측 시작 이후 가입자)을 쓴다.
    계측 이전 기존 사용자는 created_at 이 NULL 이라 "언제 가입했는지" 자체를 모르므로
    total_users 를 분모로 쓰면 활성화율이 실제보다 낮게 왜곡된다.
    """
    total_users = db.query(func.count(models.User.id)).scalar() or 0

    with_created_at = (
        db.query(func.count(models.User.id))
        .filter(models.User.created_at.isnot(None))
        .scalar()
        or 0
    )

    profile_complete = (
        db.query(func.count(models.User.id))
        .filter(
            models.User.created_at.isnot(None),
            models.User.profile_completed_at.isnot(None),
        )
        .scalar()
        or 0
    )

    activated = (
        db.query(func.count(models.User.id))
        .filter(
            models.User.created_at.isnot(None),
            models.User.first_activation_at.isnot(None),
        )
        .scalar()
        or 0
    )

    # ── 최근 days 일: 일별 가입/프로필완성/활성화 시리즈 (created_at 기준) ──
    since = _utcnow() - timedelta(days=days)
    signup_rows = (
        db.query(
            func.date(models.User.created_at).label("d"),
            func.count(models.User.id).label("cnt"),
        )
        .filter(models.User.created_at >= since)
        .group_by(func.date(models.User.created_at))
        .all()
    )
    profile_rows = (
        db.query(
            func.date(models.User.created_at).label("d"),
            func.count(models.User.id).label("cnt"),
        )
        .filter(
            models.User.created_at >= since,
            models.User.profile_completed_at.isnot(None),
        )
        .group_by(func.date(models.User.created_at))
        .all()
    )
    activated_rows = (
        db.query(
            func.date(models.User.created_at).label("d"),
            func.count(models.User.id).label("cnt"),
        )
        .filter(
            models.User.created_at >= since,
            models.User.first_activation_at.isnot(None),
        )
        .group_by(func.date(models.User.created_at))
        .all()
    )
    signups_by_date = {str(r.d): int(r.cnt or 0) for r in signup_rows}
    profile_by_date = {str(r.d): int(r.cnt or 0) for r in profile_rows}
    activated_by_date = {str(r.d): int(r.cnt or 0) for r in activated_rows}

    today = _utcnow().date()
    start_date = (since).date()
    num_days = (today - start_date).days + 1
    daily = []
    for i in range(num_days):
        d = (start_date + timedelta(days=i)).isoformat()
        daily.append({
            "date": d,
            "signups": signups_by_date.get(d, 0),
            "profile_complete": profile_by_date.get(d, 0),
            "activated": activated_by_date.get(d, 0),
        })

    return {
        "total_users": int(total_users),
        "with_created_at": int(with_created_at),
        "profile_complete": int(profile_complete),
        "profile_complete_pct": _pct(profile_complete, with_created_at),
        "activated": int(activated),
        "activated_pct": _pct(activated, with_created_at),
        "daily": daily,
    }
