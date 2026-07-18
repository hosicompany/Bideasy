"""
관리자 리드 대시보드 API
=========================
무료 자격 진단 리드의 획득·전환 퍼널을 집계.
attribution(가입→유료)의 앞단계(리드→가입)를 같은 스타일로 집계한다.

Endpoints:
- GET /admin/leads/stats — 총 리드·전환·전환율 + status/업종 분해 + 일별 시리즈 + 최근 리드
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.core.security import require_admin
from app.db import models
from app.db.session import get_db

router = APIRouter()

_CONVERTED = models.Lead.converted_user_id.isnot(None)


@router.get("/leads/stats")
def lead_stats(
    days: int = Query(30, ge=7, le=365, description="일별 시리즈·최근 목록 기간"),
    db: Session = Depends(get_db),
    _admin=Depends(require_admin),
):
    """리드 획득·전환 퍼널 집계.

    - 총/전환은 누적(전체 기간), 일별 시리즈·최근 목록은 최근 `days` 일.
    - 전환 = converted_user_id 존재(가입 시 link_leads_to_user 가 세팅).
    """
    # ── 누적 헤드라인: 총 리드·전환·전환율 ──
    total_leads = db.query(func.count(models.Lead.id)).scalar() or 0
    converted_leads = (
        db.query(func.count(models.Lead.id)).filter(_CONVERTED).scalar() or 0
    )
    conversion_pct = (
        round(converted_leads / total_leads * 100, 1) if total_leads else 0.0
    )

    # ── nurture_status 분해 ──
    status_rows = (
        db.query(
            models.Lead.nurture_status.label("status"),
            func.count(models.Lead.id).label("count"),
        )
        .group_by(models.Lead.nurture_status)
        .order_by(func.count(models.Lead.id).desc())
        .all()
    )
    by_status = [
        {"status": r.status or "(none)", "count": int(r.count or 0)}
        for r in status_rows
    ]

    # ── 업종별 리드·전환 (상위 10) ──
    industry_rows = (
        db.query(
            models.Lead.industry.label("industry"),
            func.count(models.Lead.id).label("leads"),
            func.coalesce(
                func.sum(case((_CONVERTED, 1), else_=0)), 0
            ).label("converted"),
        )
        .group_by(models.Lead.industry)
        .order_by(func.count(models.Lead.id).desc())
        .limit(10)
        .all()
    )
    by_industry = []
    for r in industry_rows:
        leads = int(r.leads or 0)
        conv = int(r.converted or 0)
        by_industry.append({
            "industry": r.industry or "(unknown)",
            "leads": leads,
            "converted": conv,
            "conversion_pct": round(conv / leads * 100, 1) if leads else 0.0,
        })

    # ── 최근 days 일: 일별 획득·전환 시리즈 ──
    since = datetime.now(timezone.utc) - timedelta(days=days)
    daily_rows = (
        db.query(
            func.date(models.Lead.created_at).label("d"),
            func.count(models.Lead.id).label("leads"),
            func.coalesce(
                func.sum(case((_CONVERTED, 1), else_=0)), 0
            ).label("converted"),
        )
        .filter(models.Lead.created_at >= since)
        .group_by(func.date(models.Lead.created_at))
        .order_by(func.date(models.Lead.created_at))
        .all()
    )
    daily = [
        {"date": str(r.d), "leads": int(r.leads or 0), "converted": int(r.converted or 0)}
        for r in daily_rows
    ]

    # ── 최근 리드 20건 ──
    recent_rows = (
        db.query(models.Lead)
        .order_by(models.Lead.created_at.desc())
        .limit(20)
        .all()
    )
    recent = [
        {
            "id": lead.id,
            "email": lead.email,
            "industry": lead.industry,
            "region": lead.region,
            "matched_count": lead.matched_count,
            "nurture_status": lead.nurture_status,
            "converted": lead.converted_user_id is not None,
            "converted_user_id": lead.converted_user_id,
            "created_at": lead.created_at.isoformat() if lead.created_at else None,
        }
        for lead in recent_rows
    ]

    return {
        "total_leads": int(total_leads),
        "converted_leads": int(converted_leads),
        "conversion_pct": conversion_pct,
        "by_status": by_status,
        "by_industry": by_industry,
        "range_days": days,
        "daily": daily,
        "recent": recent,
    }
