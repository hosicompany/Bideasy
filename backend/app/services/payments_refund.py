"""
관리자 결제 환불 서비스
========================
Toss Payments `/v1/payments/{paymentKey}/cancel` 호출 + DB 기록.

Idempotency:
- 호출 직전 PaymentOrder.refunded_at 검사 → 이미 있으면 409
- DB 우선 commit (refund_amount/refunded_at) → Toss 호출 → 응답 후
  refund_payment_key 업데이트
- Toss 응답 실패 시 보상 트랜잭션 (refunded_at = None)

부분 환불 지원 (cancelAmount). 누적 추적은 refund_amount 합계.
환불 후 tier 회수 옵션 (revoke_tier=True): user.tier=free, expires=now.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.db import models
from app.schemas.subscription import TIER_FREE

logger = get_logger(__name__)

TOSS_CANCEL_URL_TEMPLATE = "https://api.tosspayments.com/v1/payments/{key}/cancel"


async def refund_order(
    db: Session,
    order: models.PaymentOrder,
    amount: Optional[int] = None,
    reason: str = "관리자 환불",
    revoke_tier: bool = False,
) -> dict:
    """결제 환불 (전액 또는 부분).

    Args:
        db: Session (호출자가 commit 책임)
        order: 대상 PaymentOrder (status=CONFIRMED 필수)
        amount: 환불 금액. None 이면 전액 환불 (order.amount - 기존 refund_amount)
        reason: 환불 사유 (Toss API + DB 모두 기록)
        revoke_tier: True 면 사용자 tier=free + subscription_expires_at=now

    Returns:
        { "order_id", "refund_amount", "refunded_at", "toss_response": {...} }

    Raises:
        HTTPException 400: status != CONFIRMED 또는 payment_key 없음
        HTTPException 409: 이미 환불됨 (refunded_at != None)
        HTTPException 502: Toss API 호출 실패
    """
    if order.status != "CONFIRMED":
        raise HTTPException(400, detail=f"환불 가능한 상태가 아니에요 (현재: {order.status})")
    if not order.payment_key:
        raise HTTPException(400, detail="결제 키가 없어 환불할 수 없어요 (Toss 미연동 주문)")
    if order.refunded_at is not None:
        raise HTTPException(409, detail="이미 환불 처리된 주문이에요")

    already_refunded = order.refund_amount or 0
    refundable = order.amount - already_refunded
    if refundable <= 0:
        raise HTTPException(409, detail="환불 가능 잔액이 없어요")

    if amount is None:
        amount = refundable
    if amount <= 0:
        raise HTTPException(400, detail="환불 금액은 0보다 커야 해요")
    if amount > refundable:
        raise HTTPException(
            400,
            detail=f"환불 금액({amount:,})이 가능 잔액({refundable:,})을 초과해요",
        )

    now = datetime.now(timezone.utc)

    # ── 1) DB 우선 기록 (보상 가능하게) ──────────────────────
    order.refund_amount = already_refunded + amount
    order.refund_reason = reason
    # 전액 환불일 때만 refunded_at 마크 (부분 환불은 누적 추적)
    is_full_refund = order.refund_amount >= order.amount
    if is_full_refund:
        order.refunded_at = now
    db.commit()

    # ── 2) Toss 환불 API 호출 ─────────────────────────────
    cancel_url = TOSS_CANCEL_URL_TEMPLATE.format(key=order.payment_key)
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                cancel_url,
                json={
                    "cancelReason": reason,
                    "cancelAmount": amount,
                },
                auth=(settings.TOSS_SECRET_KEY, ""),
                headers={"Content-Type": "application/json"},
                timeout=15.0,
            )
    except Exception as e:
        # 네트워크 오류 → 보상
        order.refund_amount = already_refunded or None
        order.refunded_at = None
        order.refund_reason = None
        db.commit()
        logger.error(f"Toss 환불 네트워크 오류: order={order.order_id}, err={e}")
        raise HTTPException(502, detail=f"Toss 환불 API 호출 실패: {e}")

    if resp.status_code != 200:
        # API 실패 → 보상
        order.refund_amount = already_refunded or None
        order.refunded_at = None
        order.refund_reason = None
        db.commit()
        try:
            err_body = resp.json()
            err_msg = err_body.get("message", resp.text)
        except Exception:
            err_msg = resp.text
        logger.error(f"Toss 환불 거부: order={order.order_id}, status={resp.status_code}, msg={err_msg}")
        raise HTTPException(502, detail=f"Toss 환불 거부: {err_msg}")

    toss_response = resp.json()

    # Toss 응답에서 환불 paymentKey 추출 (cancels 배열 마지막 항목)
    refund_key = None
    cancels = toss_response.get("cancels", [])
    if cancels:
        refund_key = cancels[-1].get("transactionKey") or cancels[-1].get("paymentKey")
    order.refund_payment_key = refund_key

    # ── 3) 옵션: tier 회수 ─────────────────────────────────
    if revoke_tier and is_full_refund and order.user_id:
        user = db.query(models.User).filter(models.User.id == order.user_id).first()
        if user:
            user.tier = TIER_FREE
            user.subscription_expires_at = now
            logger.info(f"Tier 회수: user_id={user.id}, was={user.tier}")

    db.commit()

    logger.info(
        f"환불 완료: order={order.order_id}, amount={amount}, "
        f"is_full={is_full_refund}, tier_revoked={revoke_tier}"
    )

    return {
        "order_id": order.order_id,
        "refund_amount": amount,
        "total_refunded": order.refund_amount,
        "is_full_refund": is_full_refund,
        "refunded_at": order.refunded_at.isoformat() if order.refunded_at else None,
        "refund_payment_key": refund_key,
        "toss_response": toss_response,
    }
