import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db import models
from app.schemas import payment as payment_schemas
from app.schemas.subscription import (
    SubscribeRequest,
    SubscribeOrderResponse,
    SubscriptionInfo,
    TIER_FREE,
    TIER_PRO,
    TIER_PRO_PLUS,
    MONTHLY_PRICES,
    ANNUAL_MONTHLY_PRICES,
    TIER_DISPLAY_NAMES,
)
from app.core.security import get_current_user
from app.core.config import settings
from app.core.logging import get_logger
from app.core.analytics import log_event

logger = get_logger(__name__)

router = APIRouter()

TOSS_CONFIRM_URL = "https://api.tosspayments.com/v1/payments/confirm"


@router.post("/create-order", response_model=payment_schemas.CreateOrderResponse)
def create_order(
    request: payment_schemas.CreateOrderRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """결제 주문 생성 (프론트에서 Toss SDK 호출 전)"""
    if request.amount not in payment_schemas.ALLOWED_AMOUNTS:
        raise HTTPException(
            status_code=400,
            detail=f"허용된 금액: {payment_schemas.ALLOWED_AMOUNTS}",
        )

    ts = int(datetime.now(timezone.utc).timestamp())
    rand = secrets.token_hex(4)
    order_id = f"BIDEASY_{current_user.id}_{ts}_{rand}"

    order = models.PaymentOrder(
        user_id=current_user.id,
        order_id=order_id,
        amount=request.amount,
        status="PENDING",
    )
    db.add(order)
    db.commit()

    customer_name = current_user.company_name or current_user.email or "BidEasy User"
    logger.info(f"Payment order created: order_id={order_id}, amount={request.amount}")
    log_event("payment_order_created", user_id=current_user.id, amount=request.amount)

    return payment_schemas.CreateOrderResponse(
        order_id=order_id,
        amount=request.amount,
        order_name=f"BidEasy 포인트 {request.amount:,}원",
        customer_name=customer_name,
        toss_client_key=settings.TOSS_CLIENT_KEY,
    )


@router.get("/success")
async def payment_success(
    paymentKey: str = Query(...),
    orderId: str = Query(...),
    amount: int = Query(...),
    db: Session = Depends(get_db),
):
    """토스 결제 성공 콜백 → Confirm API → 포인트 적립 → 프론트 리다이렉트"""
    order = (
        db.query(models.PaymentOrder)
        .filter(models.PaymentOrder.order_id == orderId)
        .first()
    )
    if not order:
        logger.warning(f"Payment success: order not found: {orderId}")
        return RedirectResponse(
            f"{settings.FRONTEND_URL}/?payment=fail&message=주문을 찾을 수 없습니다"
        )

    # Idempotency: already confirmed
    if order.status == "CONFIRMED":
        logger.info(f"Payment already confirmed: {orderId}")
        params = urlencode({"payment": "success", "amount": str(order.amount)})
        return RedirectResponse(f"{settings.FRONTEND_URL}/?{params}")

    # Amount tampering check
    if order.amount != amount:
        logger.warning(f"Payment amount mismatch: order={order.amount}, callback={amount}")
        order.status = "FAILED"
        order.fail_reason = "Amount mismatch"
        db.commit()
        return RedirectResponse(
            f"{settings.FRONTEND_URL}/?payment=fail&message=결제 금액이 일치하지 않습니다"
        )

    # Toss Confirm API
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            TOSS_CONFIRM_URL,
            json={
                "paymentKey": paymentKey,
                "orderId": orderId,
                "amount": amount,
            },
            auth=(settings.TOSS_SECRET_KEY, ""),
            headers={"Content-Type": "application/json"},
        )

    if resp.status_code != 200:
        error_data = resp.json()
        fail_msg = error_data.get("message", "결제 승인에 실패했습니다")
        logger.warning(f"Toss confirm failed: {resp.status_code} {error_data}")
        order.status = "FAILED"
        order.fail_reason = fail_msg[:500]
        db.commit()
        return RedirectResponse(
            f"{settings.FRONTEND_URL}/?payment=fail&message={fail_msg}"
        )

    # Confirm success — credit points
    toss_data = resp.json()
    user = db.query(models.User).filter(models.User.id == order.user_id).first()
    user.points += order.amount
    balance_after = user.points

    tx = models.PointTransaction(
        user_id=user.id,
        amount=order.amount,
        balance_after=balance_after,
        tx_type="CHARGE",
        description=f"포인트 충전 {order.amount:,}원 (토스결제)",
    )
    db.add(tx)
    db.flush()

    order.status = "CONFIRMED"
    order.payment_key = paymentKey
    order.method = toss_data.get("method", "")
    order.point_transaction_id = tx.id
    order.confirmed_at = datetime.now(timezone.utc)
    db.commit()

    logger.info(
        f"Payment confirmed: order_id={orderId}, amount={order.amount}, user_id={user.id}"
    )
    log_event("payment_confirmed", user_id=user.id, amount=order.amount)
    params = urlencode({"payment": "success", "amount": str(order.amount)})
    return RedirectResponse(f"{settings.FRONTEND_URL}/?{params}")


@router.get("/fail")
def payment_fail(
    code: str = Query(default=""),
    message: str = Query(default="결제가 취소되었습니다"),
    orderId: str = Query(default=""),
    db: Session = Depends(get_db),
):
    """토스 결제 실패/취소 콜백 → 프론트 리다이렉트"""
    if orderId:
        order = (
            db.query(models.PaymentOrder)
            .filter(models.PaymentOrder.order_id == orderId)
            .first()
        )
        if order and order.status == "PENDING":
            order.status = "FAILED"
            order.fail_reason = f"[{code}] {message}"[:500]
            db.commit()
            logger.info(f"Payment failed: order_id={orderId}, code={code}")

    return RedirectResponse(
        f"{settings.FRONTEND_URL}/?payment=fail&message={message}"
    )


# ─── Subscription Endpoints ───


@router.post("/subscribe", response_model=SubscribeOrderResponse)
def create_subscription_order(
    request: SubscribeRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """구독 결제 주문 생성 (Toss SDK 호출 전)"""
    if request.tier not in (TIER_PRO, TIER_PRO_PLUS):
        raise HTTPException(status_code=400, detail="유효하지 않은 구독 티어입니다")

    if request.billing_cycle not in ("monthly", "annual"):
        raise HTTPException(status_code=400, detail="유효하지 않은 결제 주기입니다")

    prices = ANNUAL_MONTHLY_PRICES if request.billing_cycle == "annual" else MONTHLY_PRICES
    amount = prices[request.tier]
    if request.billing_cycle == "annual":
        amount = amount * 10  # 10 months (2 months free)

    ts = int(datetime.now(timezone.utc).timestamp())
    rand = secrets.token_hex(4)
    order_id = f"SUB_{current_user.id}_{request.tier}_{ts}_{rand}"

    order = models.PaymentOrder(
        user_id=current_user.id,
        order_id=order_id,
        amount=amount,
        status="PENDING",
    )
    db.add(order)
    db.commit()

    tier_display = TIER_DISPLAY_NAMES.get(request.tier, request.tier)
    cycle_display = "연간" if request.billing_cycle == "annual" else "월간"
    customer_name = current_user.company_name or current_user.email or "BidEasy User"

    logger.info(
        f"Subscription order created: order_id={order_id}, "
        f"tier={request.tier}, cycle={request.billing_cycle}, amount={amount}"
    )
    log_event("subscription_order_created", user_id=current_user.id, tier=request.tier, cycle=request.billing_cycle, amount=amount)

    return SubscribeOrderResponse(
        order_id=order_id,
        amount=amount,
        order_name=f"BidEasy {tier_display} 구독 ({cycle_display})",
        customer_name=customer_name,
        toss_client_key=settings.TOSS_CLIENT_KEY,
        tier=request.tier,
        billing_cycle=request.billing_cycle,
    )


@router.get("/subscribe/success")
async def subscription_success(
    paymentKey: str = Query(...),
    orderId: str = Query(...),
    amount: int = Query(...),
    db: Session = Depends(get_db),
):
    """구독 결제 성공 콜백 → Confirm → 티어 업그레이드 → 프론트 리다이렉트"""
    order = (
        db.query(models.PaymentOrder)
        .filter(models.PaymentOrder.order_id == orderId)
        .first()
    )
    if not order:
        logger.warning(f"Subscription success: order not found: {orderId}")
        return RedirectResponse(
            f"{settings.FRONTEND_URL}/?payment=fail&message=주문을 찾을 수 없습니다"
        )

    if order.status == "CONFIRMED":
        params = urlencode({"payment": "success", "amount": str(order.amount), "type": "subscription"})
        return RedirectResponse(f"{settings.FRONTEND_URL}/?{params}")

    if order.amount != amount:
        logger.warning(f"Subscription amount mismatch: order={order.amount}, callback={amount}")
        order.status = "FAILED"
        order.fail_reason = "Amount mismatch"
        db.commit()
        return RedirectResponse(
            f"{settings.FRONTEND_URL}/?payment=fail&message=결제 금액이 일치하지 않습니다"
        )

    # Toss Confirm API
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            TOSS_CONFIRM_URL,
            json={"paymentKey": paymentKey, "orderId": orderId, "amount": amount},
            auth=(settings.TOSS_SECRET_KEY, ""),
            headers={"Content-Type": "application/json"},
        )

    if resp.status_code != 200:
        error_data = resp.json()
        fail_msg = error_data.get("message", "결제 승인에 실패했습니다")
        logger.warning(f"Toss subscription confirm failed: {resp.status_code} {error_data}")
        order.status = "FAILED"
        order.fail_reason = fail_msg[:500]
        db.commit()
        return RedirectResponse(
            f"{settings.FRONTEND_URL}/?payment=fail&message={fail_msg}"
        )

    # Parse tier and billing cycle from order_id: SUB_{uid}_{tier}_{ts}_{rand}
    parts = orderId.split("_")
    tier = parts[2] if len(parts) >= 4 else TIER_PRO
    is_annual = order.amount >= 100_000  # annual payments are > 100k

    # Upgrade user tier
    user = db.query(models.User).filter(models.User.id == order.user_id).first()
    user.tier = tier
    days = 365 if is_annual else 30
    user.subscription_expires_at = datetime.now(timezone.utc) + timedelta(days=days)

    order.status = "CONFIRMED"
    order.payment_key = paymentKey
    order.method = resp.json().get("method", "")
    order.confirmed_at = datetime.now(timezone.utc)
    db.commit()

    logger.info(
        f"Subscription confirmed: order_id={orderId}, tier={tier}, "
        f"days={days}, user_id={user.id}"
    )
    params = urlencode({
        "payment": "success",
        "amount": str(order.amount),
        "type": "subscription",
    })
    return RedirectResponse(f"{settings.FRONTEND_URL}/?{params}")


@router.get("/subscription", response_model=SubscriptionInfo)
def get_subscription(
    current_user: models.User = Depends(get_current_user),
):
    """현재 구독 상태 조회"""
    tier = current_user.tier or TIER_FREE
    expires_at = current_user.subscription_expires_at
    is_active = tier != TIER_FREE and (
        expires_at is None or expires_at > datetime.now(timezone.utc)
    )

    # If expired, treat as free
    if not is_active and tier != TIER_FREE:
        tier = TIER_FREE

    return SubscriptionInfo(
        tier=tier,
        tier_display=TIER_DISPLAY_NAMES.get(tier, "Free"),
        expires_at=expires_at,
        is_active=is_active,
    )


@router.post("/subscribe/cancel")
def cancel_subscription(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """구독 해지 (만료일까지 사용 가능, 갱신 안 함)"""
    if (current_user.tier or TIER_FREE) == TIER_FREE:
        raise HTTPException(status_code=400, detail="현재 구독 중이 아닙니다")

    logger.info(
        f"Subscription cancelled: user_id={current_user.id}, "
        f"tier={current_user.tier}, expires_at={current_user.subscription_expires_at}"
    )

    return {
        "success": True,
        "message": "구독이 해지되었어요. 만료일까지 계속 이용 가능합니다.",
        "expires_at": current_user.subscription_expires_at.isoformat()
        if current_user.subscription_expires_at else None,
    }
