"""
관리자 사용자 관리 API
========================
Endpoints:
- GET    /admin/users                     검색·필터·페이지네이션
- GET    /admin/users/{user_id}           상세
- PATCH  /admin/users/{user_id}/tier      tier 변경 (수동 부여)
- POST   /admin/users/{user_id}/extend-trial  체험 N일 연장
- POST   /admin/users/{user_id}/expire-trial  체험 즉시 만료
- DELETE /admin/users/{user_id}            cascade 삭제 (force 옵션)
- POST   /admin/users/{user_id}/grant-points  포인트 수동 지급
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.core.security import require_admin
from app.db import models
from app.db.session import get_db
from app.schemas.subscription import (
    TIER_FREE,
    VALID_TIERS,
    get_effective_tier,
    is_trial_active,
    trial_days_remaining,
)
from app.services.admin_user_delete import delete_user_cascade

from . import _common

router = APIRouter()


# ─── 응답 스키마 ───────────────────────────────────────────

class AdminUserItem(BaseModel):
    id: int
    email: Optional[str] = None
    company_name: str = ""
    ceo_name: Optional[str] = None
    tier: str = "free"
    effective_tier: str = "free"
    is_admin: bool = False
    is_trial_active: bool = False
    trial_days_remaining: int = 0
    points: int = 0
    subscription_expires_at: Optional[str] = None
    trial_started_at: Optional[str] = None
    trial_expires_at: Optional[str] = None
    social_provider: Optional[str] = None


class AdminUserDetail(AdminUserItem):
    licenses: Optional[str] = None
    location: Optional[str] = None
    capacity_cost: int = 0
    performance_record: int = 0
    profile_image_url: Optional[str] = None
    # 결제·포인트 요약
    total_paid: int = 0
    total_refunded: int = 0
    bids_count: int = 0


def _row_to_item(u: models.User) -> AdminUserItem:
    eff = get_effective_tier(u)
    return AdminUserItem(
        id=u.id,
        email=u.email,
        company_name=u.company_name or "",
        ceo_name=u.ceo_name,
        tier=u.tier or "free",
        effective_tier=eff,
        is_admin=bool(u.is_admin),
        is_trial_active=is_trial_active(u),
        trial_days_remaining=trial_days_remaining(u),
        points=u.points or 0,
        subscription_expires_at=u.subscription_expires_at.isoformat() if u.subscription_expires_at else None,
        trial_started_at=u.trial_started_at.isoformat() if u.trial_started_at else None,
        trial_expires_at=u.trial_expires_at.isoformat() if u.trial_expires_at else None,
        social_provider=u.social_provider,
    )


# ─── GET /admin/users (목록) ──────────────────────────────

@router.get("/users")
def list_users(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
    search: Optional[str] = Query(None, description="이메일·회사명·대표자명 부분일치"),
    tier: Optional[str] = Query(None, description="free|pro|pro_plus"),
    trial: Optional[str] = Query(None, description="active|expired|none"),
    is_admin: Optional[bool] = Query(None),
    sort: Optional[str] = Query("-id", description="-id, id, -trial_expires_at 등"),
    db: Session = Depends(get_db),
    _admin=Depends(require_admin),
):
    q = db.query(models.User)
    if search:
        like = f"%{search}%"
        q = q.filter(or_(
            models.User.email.ilike(like),
            models.User.company_name.ilike(like),
            models.User.ceo_name.ilike(like),
        ))
    if tier and tier in VALID_TIERS:
        q = q.filter(models.User.tier == tier)
    if is_admin is not None:
        q = q.filter(models.User.is_admin == is_admin)
    now = datetime.now(timezone.utc)
    if trial == "active":
        q = q.filter(models.User.trial_expires_at.isnot(None), models.User.trial_expires_at > now)
    elif trial == "expired":
        q = q.filter(models.User.trial_started_at.isnot(None),
                     or_(models.User.trial_expires_at.is_(None),
                         models.User.trial_expires_at <= now))
    elif trial == "none":
        q = q.filter(models.User.trial_started_at.is_(None))

    allowed = {
        "id": models.User.id,
        "trial_expires_at": models.User.trial_expires_at,
        "trial_started_at": models.User.trial_started_at,
        "points": models.User.points,
        "tier": models.User.tier,
    }
    sort_attr, sort_dir = _common.parse_sort(sort, allowed, models.User.id, "desc")

    result = _common.paginate(q, page, size, sort_attr, sort_dir)
    return {
        "items": [_row_to_item(u).model_dump() for u in result["items"]],
        "total": result["total"],
        "page": result["page"],
        "size": result["size"],
        "total_pages": result["total_pages"],
    }


# ─── GET /admin/users/{id} (상세) ─────────────────────────

@router.get("/users/{user_id}")
def get_user_detail(
    user_id: int,
    db: Session = Depends(get_db),
    _admin=Depends(require_admin),
) -> dict:
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(404, "사용자 없음")

    # 결제 요약
    paid = db.query(func.coalesce(func.sum(models.PaymentOrder.amount), 0)).filter(
        models.PaymentOrder.user_id == user_id,
        models.PaymentOrder.status == "CONFIRMED",
    ).scalar() or 0
    refunded = db.query(func.coalesce(func.sum(models.PaymentOrder.refund_amount), 0)).filter(
        models.PaymentOrder.user_id == user_id,
        models.PaymentOrder.refund_amount.isnot(None),
    ).scalar() or 0
    bids_count = db.query(func.count(models.UserBid.id)).filter(
        models.UserBid.user_id == user_id
    ).scalar() or 0

    base = _row_to_item(user)
    detail = AdminUserDetail(
        **base.model_dump(),
        licenses=user.licenses,
        location=user.location,
        capacity_cost=user.capacity_cost or 0,
        performance_record=user.performance_record or 0,
        profile_image_url=user.profile_image_url,
        total_paid=int(paid),
        total_refunded=int(refunded),
        bids_count=int(bids_count),
    )

    # 최근 결제·포인트 거래 5건씩
    recent_payments = db.query(models.PaymentOrder).filter(
        models.PaymentOrder.user_id == user_id
    ).order_by(models.PaymentOrder.created_at.desc()).limit(5).all()
    recent_points = db.query(models.PointTransaction).filter(
        models.PointTransaction.user_id == user_id
    ).order_by(models.PointTransaction.created_at.desc()).limit(5).all()

    return {
        **detail.model_dump(),
        "recent_payments": [
            {
                "order_id": p.order_id,
                "amount": p.amount,
                "status": p.status,
                "method": p.method,
                "confirmed_at": p.confirmed_at.isoformat() if p.confirmed_at else None,
                "refund_amount": p.refund_amount,
                "refunded_at": p.refunded_at.isoformat() if p.refunded_at else None,
            }
            for p in recent_payments
        ],
        "recent_points": [
            {
                "amount": t.amount,
                "balance_after": t.balance_after,
                "tx_type": t.tx_type,
                "description": t.description,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
            for t in recent_points
        ],
    }


# ─── PATCH /admin/users/{id}/tier ─────────────────────────

class TierUpdateRequest(BaseModel):
    tier: str = Field(..., description="free|pro|pro_plus")
    expires_at: Optional[datetime] = Field(None, description="구독 만료일 (None=무기한 또는 free 시 무시)")
    reason: Optional[str] = None


@router.patch("/users/{user_id}/tier")
def update_user_tier(
    user_id: int,
    body: TierUpdateRequest,
    db: Session = Depends(get_db),
    _admin=Depends(require_admin),
):
    if body.tier not in VALID_TIERS:
        raise HTTPException(400, f"유효하지 않은 tier: {body.tier}")
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(404, "사용자 없음")

    user.tier = body.tier
    if body.tier == TIER_FREE:
        user.subscription_expires_at = None
    else:
        user.subscription_expires_at = body.expires_at  # None 이면 무기한

    db.commit()
    return {"ok": True, "user_id": user.id, "tier": user.tier, "expires_at": user.subscription_expires_at}


# ─── POST /admin/users/{id}/extend-trial ───────────────────

class ExtendTrialRequest(BaseModel):
    days: int = Field(..., ge=1, le=365)


@router.post("/users/{user_id}/extend-trial")
def extend_user_trial(
    user_id: int,
    body: ExtendTrialRequest,
    db: Session = Depends(get_db),
    _admin=Depends(require_admin),
):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(404, "사용자 없음")

    now = datetime.now(timezone.utc)
    if user.trial_started_at is None:
        user.trial_started_at = now
    # 기준점: 현재 만료일이 미래면 거기서 +days, 아니면 now +days
    base = user.trial_expires_at
    if base is not None and base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)
    if base is None or base < now:
        base = now
    user.trial_expires_at = base + timedelta(days=body.days)

    db.commit()
    return {
        "ok": True,
        "user_id": user.id,
        "trial_expires_at": user.trial_expires_at.isoformat(),
    }


# ─── POST /admin/users/{id}/expire-trial ───────────────────

@router.post("/users/{user_id}/expire-trial")
def expire_user_trial(
    user_id: int,
    db: Session = Depends(get_db),
    _admin=Depends(require_admin),
):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(404, "사용자 없음")

    now = datetime.now(timezone.utc)
    if user.trial_started_at is None:
        user.trial_started_at = now
    user.trial_expires_at = now

    db.commit()
    return {"ok": True, "user_id": user.id, "trial_expires_at": now.isoformat()}


# ─── DELETE /admin/users/{id} ─────────────────────────────

@router.delete("/users/{user_id}")
def delete_user(
    user_id: int,
    force: bool = Query(False, description="활성 구독 있어도 강제 삭제"),
    db: Session = Depends(get_db),
    admin: models.User = Depends(require_admin),
):
    # 자기 자신 삭제 금지
    if admin.id == user_id:
        raise HTTPException(400, "본인 계정은 삭제할 수 없어요")

    result = delete_user_cascade(db, user_id, force=force)
    db.commit()
    return {"ok": True, **result}


# ─── POST /admin/users/{id}/grant-points ─────────────────

class GrantPointsRequest(BaseModel):
    amount: int = Field(..., ge=1, le=1_000_000)
    reason: str = Field(..., min_length=1, max_length=255)


@router.post("/users/{user_id}/grant-points")
def grant_points(
    user_id: int,
    body: GrantPointsRequest,
    db: Session = Depends(get_db),
    _admin=Depends(require_admin),
):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(404, "사용자 없음")

    new_balance = (user.points or 0) + body.amount
    user.points = new_balance
    tx = models.PointTransaction(
        user_id=user.id,
        amount=body.amount,
        balance_after=new_balance,
        tx_type="ADMIN_GRANT",
        description=f"운영자 지급: {body.reason}",
    )
    db.add(tx)
    db.commit()
    return {"ok": True, "user_id": user.id, "new_balance": new_balance}
