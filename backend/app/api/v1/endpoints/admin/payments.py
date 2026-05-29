"""
관리자 결제 관리 API
=====================
Endpoints:
- GET  /admin/payments                  검색·필터·페이지네이션
- GET  /admin/payments/{order_id}       상세
- POST /admin/payments/{order_id}/refund  Toss 환불 (전액·부분)
- POST /admin/payments/cleanup-pending  24h+ PENDING → FAILED 일괄
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.core.security import require_admin
from app.db import models
from app.db.session import get_db
from app.services.payments_refund import refund_order

from . import _common

logger = get_logger(__name__)
router = APIRouter()


# ─── GET /admin/payments ──────────────────────────────────

@router.get("/payments")
def list_payments(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
    search: Optional[str] = Query(None, description="order_id·payment_key 부분일치"),
    status_filter: Optional[str] = Query(None, alias="status",
        description="PENDING|CONFIRMED|FAILED"),
    refunded: Optional[bool] = Query(None, description="환불 여부 필터"),
    from_date: Optional[datetime] = Query(None, alias="from"),
    to_date: Optional[datetime] = Query(None, alias="to"),
    sort: Optional[str] = Query("-created_at"),
    db: Session = Depends(get_db),
    _admin=Depends(require_admin),
):
    q = db.query(models.PaymentOrder)
    if search:
        like = f"%{search}%"
        q = q.filter(or_(
            models.PaymentOrder.order_id.ilike(like),
            models.PaymentOrder.payment_key.ilike(like),
        ))
    if status_filter:
        q = q.filter(models.PaymentOrder.status == status_filter)
    if refunded is True:
        q = q.filter(models.PaymentOrder.refunded_at.isnot(None))
    elif refunded is False:
        q = q.filter(models.PaymentOrder.refunded_at.is_(None))
    if from_date:
        q = q.filter(models.PaymentOrder.created_at >= from_date)
    if to_date:
        q = q.filter(models.PaymentOrder.created_at <= to_date)

    allowed = {
        "created_at": models.PaymentOrder.created_at,
        "confirmed_at": models.PaymentOrder.confirmed_at,
        "amount": models.PaymentOrder.amount,
    }
    sort_attr, sort_dir = _common.parse_sort(sort, allowed, models.PaymentOrder.created_at, "desc")
    result = _common.paginate(q, page, size, sort_attr, sort_dir)

    items = []
    for p in result["items"]:
        items.append({
            "id": p.id,
            "order_id": p.order_id,
            "order_kind": "subscription" if p.order_id.startswith("SUB_") else "points",
            "user_id": p.user_id,  # SET NULL 정책으로 None 가능
            "amount": p.amount,
            "status": p.status,
            "method": p.method,
            "created_at": p.created_at.isoformat() if p.created_at else None,
            "confirmed_at": p.confirmed_at.isoformat() if p.confirmed_at else None,
            "refund_amount": p.refund_amount,
            "refunded_at": p.refunded_at.isoformat() if p.refunded_at else None,
            "fail_reason": p.fail_reason,
        })
    return {
        "items": items,
        "total": result["total"],
        "page": result["page"],
        "size": result["size"],
        "total_pages": result["total_pages"],
    }


# ─── GET /admin/payments/{order_id} ───────────────────────

@router.get("/payments/{order_id}")
def get_payment_detail(
    order_id: str,
    db: Session = Depends(get_db),
    _admin=Depends(require_admin),
):
    order = db.query(models.PaymentOrder).filter(
        models.PaymentOrder.order_id == order_id
    ).first()
    if not order:
        raise HTTPException(404, "주문 없음")

    user_summary = None
    if order.user_id:
        u = db.query(models.User).filter(models.User.id == order.user_id).first()
        if u:
            user_summary = {
                "id": u.id,
                "email": u.email,
                "company_name": u.company_name,
                "tier": u.tier,
            }

    return {
        "id": order.id,
        "order_id": order.order_id,
        "order_kind": "subscription" if order.order_id.startswith("SUB_") else "points",
        "user": user_summary,
        "user_id": order.user_id,
        "amount": order.amount,
        "status": order.status,
        "payment_key": order.payment_key,
        "method": order.method,
        "created_at": order.created_at.isoformat() if order.created_at else None,
        "confirmed_at": order.confirmed_at.isoformat() if order.confirmed_at else None,
        "fail_reason": order.fail_reason,
        "refund_amount": order.refund_amount,
        "refund_reason": order.refund_reason,
        "refunded_at": order.refunded_at.isoformat() if order.refunded_at else None,
        "refund_payment_key": order.refund_payment_key,
    }


# ─── POST /admin/payments/{order_id}/refund ───────────────

class RefundRequest(BaseModel):
    amount: Optional[int] = Field(None, ge=1, description="None=전액")
    reason: str = Field(..., min_length=1, max_length=500)
    revoke_tier: bool = Field(False, description="전액 환불 시 사용자 tier=free 회수")


@router.post("/payments/{order_id}/refund")
async def refund_payment(
    order_id: str,
    body: RefundRequest,
    db: Session = Depends(get_db),
    _admin=Depends(require_admin),
):
    order = db.query(models.PaymentOrder).filter(
        models.PaymentOrder.order_id == order_id
    ).first()
    if not order:
        raise HTTPException(404, "주문 없음")

    result = await refund_order(
        db=db,
        order=order,
        amount=body.amount,
        reason=body.reason,
        revoke_tier=body.revoke_tier,
    )
    return {"ok": True, **result}


# ─── POST /admin/payments/{order_id}/cancel-pending ───────

@router.post("/payments/{order_id}/cancel-pending")
def cancel_pending_payment(
    order_id: str,
    reason: str = Query("운영자 수동 취소", description="취소 사유"),
    db: Session = Depends(get_db),
    _admin=Depends(require_admin),
):
    """단건 PENDING 주문을 즉시 FAILED 로 전환.

    24h+ cleanup 과 별개: 운영자가 PENDING 한 건만 골라서 정리할 때.
    Toss API 호출 안 함 (결제 미완료 = 외부 영향 없음).
    """
    order = db.query(models.PaymentOrder).filter(
        models.PaymentOrder.order_id == order_id
    ).first()
    if not order:
        raise HTTPException(404, "주문 없음")
    if order.status != "PENDING":
        raise HTTPException(400, f"PENDING 만 취소 가능해요 (현재: {order.status})")
    order.status = "FAILED"
    order.fail_reason = reason
    db.commit()
    logger.info(f"[admin] 단건 PENDING 취소: order={order_id}, reason={reason}")
    return {"ok": True, "order_id": order_id, "status": "FAILED"}


# ─── POST /admin/payments/cleanup-pending ─────────────────

class CleanupRequest(BaseModel):
    hours: int = Field(24, ge=1, le=720, description="N시간 이상 PENDING 대상 (기본 24)")


@router.post("/payments/cleanup-pending")
def cleanup_pending(
    body: CleanupRequest = Body(default=None),
    db: Session = Depends(get_db),
    _admin=Depends(require_admin),
):
    cutoff_hours = body.hours if body else 24
    cutoff = datetime.now(timezone.utc) - timedelta(hours=cutoff_hours)
    rows = db.query(models.PaymentOrder).filter(
        models.PaymentOrder.status == "PENDING",
        models.PaymentOrder.created_at < cutoff,
    ).all()

    count = 0
    for r in rows:
        r.status = "FAILED"
        r.fail_reason = f"자동 정리: {cutoff_hours}시간 이상 PENDING 상태"
        count += 1
    db.commit()

    logger.info(f"[admin] cleanup-pending: {count}건 정리 (cutoff={cutoff_hours}h)")
    return {"ok": True, "cleaned": count, "cutoff_hours": cutoff_hours}
