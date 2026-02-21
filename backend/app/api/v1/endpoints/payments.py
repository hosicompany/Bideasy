import secrets
from datetime import datetime, timezone
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db import models
from app.schemas import payment as payment_schemas
from app.core.security import get_current_user
from app.core.config import settings
from app.core.logging import get_logger

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
