import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.services.billing import (
    issue_billing_key,
    charge_billing_key,
    BillingError,
)
from app.services import payple as payple_svc

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
    ANNUAL_PRICES,
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

    # 월간: 월 단위 청구, 연간: 1회 청구 (365일 유효)
    # 이전 버그: ANNUAL_MONTHLY_PRICES × 10 = 124,000원 (의도 149,000원)
    # 수정: ANNUAL_PRICES 직접 사용 (20% 할인 반영 정상 가격)
    if request.billing_cycle == "annual":
        original_amount = ANNUAL_PRICES[request.tier]
    else:
        original_amount = MONTHLY_PRICES[request.tier]

    # 첫 달 50% 할인 자동 적용 — 월간 결제 + 자격 사용자만
    # (연간은 이미 20% 할인된 가격이라 추가 win-back 적용 안 함)
    from app.schemas.subscription import (
        is_winback_eligible,
        calculate_winback_discount,
        WINBACK_REASON_CODE,
    )
    amount = original_amount
    discount_amount = None
    discount_reason = None
    if request.billing_cycle == "monthly" and is_winback_eligible(current_user, db):
        discount_amount = calculate_winback_discount(original_amount)
        amount = original_amount - discount_amount
        discount_reason = WINBACK_REASON_CODE
        logger.info(
            f"Win-back 50% applied: user={current_user.id}, "
            f"original={original_amount}, discount={discount_amount}, final={amount}"
        )

    # Idempotency — 30초 이내 같은 사용자의 같은 (tier, billing_cycle, amount) PENDING
    # 주문이 있으면 그것을 재사용. 더블 클릭·네트워크 재시도로 중복 PENDING 생성 방지.
    now = datetime.now(timezone.utc)
    # created_at 은 SQLAlchemy default 가 _utcnow() 인데 DB(PG/SQLite)는 timestamp
    # without tz 로 저장 → naive 로 비교 (timezone 정보 제거)
    recent_cutoff = (now - timedelta(seconds=30)).replace(tzinfo=None)
    existing = (
        db.query(models.PaymentOrder)
        .filter(
            models.PaymentOrder.user_id == current_user.id,
            models.PaymentOrder.status == "PENDING",
            models.PaymentOrder.amount == amount,
            models.PaymentOrder.order_id.like(f"SUB_{current_user.id}_{request.tier}_%"),
            models.PaymentOrder.created_at >= recent_cutoff,
        )
        .order_by(models.PaymentOrder.created_at.desc())
        .first()
    )
    if existing:
        logger.info(
            f"Subscription idempotency hit: reusing order={existing.order_id} "
            f"(created_at={existing.created_at})"
        )
        order_id = existing.order_id
        order = existing
    else:
        ts = int(now.timestamp())
        rand = secrets.token_hex(4)
        order_id = f"SUB_{current_user.id}_{request.tier}_{ts}_{rand}"

        order = models.PaymentOrder(
            user_id=current_user.id,
            order_id=order_id,
            amount=amount,
            status="PENDING",
            discount_amount=discount_amount,
            discount_reason=discount_reason,
        )
        db.add(order)
        db.commit()

    tier_display = TIER_DISPLAY_NAMES.get(request.tier, request.tier)
    cycle_display = "연간" if request.billing_cycle == "annual" else "월간"
    if discount_amount:
        cycle_display += " · 첫 달 50% 할인"
    customer_name = current_user.company_name or current_user.email or "BidEasy User"

    logger.info(
        f"Subscription order created: order_id={order_id}, "
        f"tier={request.tier}, cycle={request.billing_cycle}, amount={amount}"
    )
    log_event(
        "subscription_order_created",
        user_id=current_user.id,
        tier=request.tier,
        cycle=request.billing_cycle,
        amount=amount,
        discount_amount=discount_amount or 0,
        discount_reason=discount_reason,
    )

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
    # 결제 완료 → 진행 중이던 체험 종료 (유료 전환, is_trial=False)
    user.trial_expires_at = datetime.now(timezone.utc)

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
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """현재 구독 상태 조회 — 유료 구독·체험·win-back 자격 통합 반영."""
    from app.schemas.subscription import (
        get_effective_tier,
        is_trial_active,
        trial_days_remaining,
        has_used_trial,
        is_winback_eligible,
        winback_expires_at,
        WINBACK_DISCOUNT_PCT,
    )

    raw_tier = current_user.tier or TIER_FREE
    expires_at = current_user.subscription_expires_at
    # PostgreSQL 의 DateTime 컬럼은 naive 로 저장·반환됨 → aware now 와 직접 비교 시
    # "can't compare offset-naive and offset-aware datetimes" TypeError 발생.
    # naive 면 UTC 로 간주해 aware 화한 뒤 비교.
    exp_aware = expires_at
    if exp_aware is not None and exp_aware.tzinfo is None:
        exp_aware = exp_aware.replace(tzinfo=timezone.utc)
    paid_active = raw_tier != TIER_FREE and (
        exp_aware is None or exp_aware > datetime.now(timezone.utc)
    )

    # 유효 tier 는 유료/체험/Free 통합 판정
    effective_tier = get_effective_tier(current_user)
    trial_active = is_trial_active(current_user)
    # 유료 구독이 활성이면 체험으로 표시하지 않음 (유료 우선).
    # 결제 시 trial 을 종료하지만, 그 전에 결제된 계정(체험 종료 누락)도
    # 여기서 방어적으로 유료로 표시되도록 보정.
    show_trial = trial_active and not paid_active

    # Win-back 자격 (Trial 사용자 첫 결제 시 자동 50%)
    winback = is_winback_eligible(current_user, db)

    return SubscriptionInfo(
        tier=effective_tier,
        tier_display=TIER_DISPLAY_NAMES.get(effective_tier, "Free"),
        expires_at=expires_at if paid_active else None,
        is_active=paid_active or trial_active,
        is_trial=show_trial,
        trial_expires_at=current_user.trial_expires_at if show_trial else None,
        trial_days_remaining=trial_days_remaining(current_user),
        has_used_trial=has_used_trial(current_user),
        winback_eligible=winback,
        winback_expires_at=winback_expires_at(current_user) if winback else None,
        winback_discount_pct=WINBACK_DISCOUNT_PCT if winback else 0,
    )


@router.post("/subscribe/cancel")
def cancel_subscription(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """구독 해지 — 자동 갱신 중단. 남은 구독 기간은 만료일까지 유지."""
    was_auto = bool(current_user.auto_renew)
    if (current_user.tier or TIER_FREE) == TIER_FREE and not was_auto:
        raise HTTPException(status_code=400, detail="현재 구독 중이 아닙니다")

    # 자동 갱신만 끈다 (빌링키는 보관 — 재구독 시 재사용 가능).
    current_user.auto_renew = False
    db.commit()

    logger.info(
        f"Subscription cancelled (auto_renew off): user_id={current_user.id}, "
        f"tier={current_user.tier}, expires_at={current_user.subscription_expires_at}, "
        f"was_auto_renew={was_auto}"
    )
    log_event("subscription_cancelled", user_id=current_user.id, tier=current_user.tier)

    return {
        "success": True,
        "message": "자동 갱신을 해지했어요. 만료일까지 계속 이용 가능합니다.",
        "expires_at": current_user.subscription_expires_at.isoformat()
        if current_user.subscription_expires_at else None,
    }


@router.get("/history")
def get_payment_history(
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """현재 사용자의 결제 내역 (CONFIRMED 만).

    응답 항목:
      - order_id, order_kind (subscription | points), amount, status,
        method, confirmed_at, created_at
      - 마이페이지(/account) 결제 내역 테이블용
    """
    orders = (
        db.query(models.PaymentOrder)
        .filter(
            models.PaymentOrder.user_id == current_user.id,
            models.PaymentOrder.status == "CONFIRMED",
        )
        .order_by(models.PaymentOrder.created_at.desc())
        .limit(limit)
        .all()
    )

    return {
        "items": [
            {
                "order_id": o.order_id,
                "order_kind": "subscription"
                if o.order_id.startswith(("SUB_", "BILL_", "BILLR_", "PYP_", "PYPR_"))
                else "points",
                "amount": o.amount,
                "status": o.status,
                "method": o.method,
                "confirmed_at": o.confirmed_at.isoformat() if o.confirmed_at else None,
                "created_at": o.created_at.isoformat() if o.created_at else None,
            }
            for o in orders
        ],
        "total": len(orders),
    }


# ─── 자동결제(빌링) Endpoints ───
#
# 단건결제(/subscribe)와 달리, 빌링은 카드를 1회 등록(빌링키 발급)해두고 매 주기
# 자동청구한다. 흐름:
#   1) POST /payments/billing/prepare  — 주문 생성 + customerKey 발급
#   2) [프론트] tossPayments.requestBillingAuth → successUrl 콜백
#   3) GET  /payments/billing/success  — 빌링키 발급·저장 + 첫 청구 + 티어 적용
#   4) Celery 가 매일 만료 임박분을 자동청구 (billing_tasks.charge_due_subscriptions)

# 티어 ↔ 짧은 코드 (order_id 인코딩용 — pro_plus 의 '_' 파싱 모호성 회피)
_TIER_CODE = {TIER_PRO: "P", TIER_PRO_PLUS: "PP"}
_CODE_TIER = {"P": TIER_PRO, "PP": TIER_PRO_PLUS}


def _billing_customer_key(user: models.User) -> str:
    """사용자당 안정적인 customerKey 반환 (없으면 생성). 토스 규격: [A-Za-z0-9-_=.@] 2~50자."""
    if user.billing_customer_key:
        return user.billing_customer_key
    return f"BIDEASYU{user.id}{secrets.token_hex(6)}"


def _apply_subscription_after_charge(
    user: models.User, tier: str, is_annual: bool, extend_from_existing: bool = False
) -> int:
    """청구 성공 후 티어 업그레이드 + 만료일 설정. 갱신 일수 반환.

    extend_from_existing=True (자동 갱신): 남은 기간이 있으면 이어붙임 (조기청구 손해 방지).
    """
    now = datetime.now(timezone.utc)
    days = 365 if is_annual else 30
    if extend_from_existing and user.subscription_expires_at:
        cur = user.subscription_expires_at
        if cur.tzinfo is None:
            cur = cur.replace(tzinfo=timezone.utc)
        start = cur if cur > now else now
    else:
        start = now
    user.tier = tier
    user.subscription_expires_at = start + timedelta(days=days)
    return days


@router.post("/billing/prepare")
def billing_prepare(
    request: SubscribeRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """자동결제 등록 준비 — 주문 생성 + customerKey 발급.

    프론트는 응답의 customer_key 로 tossPayments.requestBillingAuth 를 호출하고,
    successUrl 에 order_id 를 실어 보낸다. (첫 청구 금액 = 응답 amount)
    """
    if request.tier not in (TIER_PRO, TIER_PRO_PLUS):
        raise HTTPException(status_code=400, detail="유효하지 않은 구독 티어입니다")
    if request.billing_cycle not in ("monthly", "annual"):
        raise HTTPException(status_code=400, detail="유효하지 않은 결제 주기입니다")

    is_annual = request.billing_cycle == "annual"
    original_amount = (ANNUAL_PRICES if is_annual else MONTHLY_PRICES)[request.tier]

    # 첫 달 50% win-back (월간 + 자격자) — 단건결제와 동일 정책
    from app.schemas.subscription import (
        is_winback_eligible,
        calculate_winback_discount,
        WINBACK_REASON_CODE,
    )

    amount = original_amount
    discount_amount = None
    discount_reason = None
    if not is_annual and is_winback_eligible(current_user, db):
        discount_amount = calculate_winback_discount(original_amount)
        amount = original_amount - discount_amount
        discount_reason = WINBACK_REASON_CODE

    # customerKey 확정·저장 (재사용)
    customer_key = _billing_customer_key(current_user)
    if not current_user.billing_customer_key:
        current_user.billing_customer_key = customer_key

    now = datetime.now(timezone.utc)
    ts = int(now.timestamp())
    rand = secrets.token_hex(4)
    cyc = "a" if is_annual else "m"
    order_id = f"BILL_{current_user.id}_{_TIER_CODE[request.tier]}_{cyc}_{ts}_{rand}"

    order = models.PaymentOrder(
        user_id=current_user.id,
        order_id=order_id,
        amount=amount,
        status="PENDING",
        discount_amount=discount_amount,
        discount_reason=discount_reason,
    )
    db.add(order)
    db.commit()

    tier_display = TIER_DISPLAY_NAMES.get(request.tier, request.tier)
    cycle_display = "연간" if is_annual else "월간"
    order_name = f"BidEasy {tier_display} 자동결제 ({cycle_display})"

    logger.info(
        f"Billing prepare: order={order_id}, user={current_user.id}, "
        f"tier={request.tier}, cycle={request.billing_cycle}, amount={amount}"
    )
    log_event(
        "billing_prepare",
        user_id=current_user.id,
        tier=request.tier,
        cycle=request.billing_cycle,
        amount=amount,
        discount_amount=discount_amount or 0,
    )

    return {
        "order_id": order_id,
        "customer_key": customer_key,
        "amount": amount,
        "order_name": order_name,
        "customer_email": current_user.email,
        "customer_name": current_user.company_name or current_user.email or "BidEasy User",
        "toss_client_key": settings.toss_billing_client_key,
        "tier": request.tier,
        "billing_cycle": request.billing_cycle,
    }


@router.get("/billing/success")
async def billing_success(
    customerKey: str = Query(...),
    authKey: str = Query(...),
    orderId: str = Query(...),
    db: Session = Depends(get_db),
):
    """빌링 인증 성공 콜백 → 빌링키 발급·저장 → 첫 청구 → 티어 적용 → 프론트 리다이렉트."""
    order = (
        db.query(models.PaymentOrder)
        .filter(models.PaymentOrder.order_id == orderId)
        .first()
    )
    if not order:
        logger.warning(f"Billing success: order not found: {orderId}")
        return RedirectResponse(
            f"{settings.FRONTEND_URL}/?payment=fail&message=주문을 찾을 수 없습니다"
        )

    if order.status == "CONFIRMED":
        params = urlencode({"payment": "success", "amount": str(order.amount), "type": "billing"})
        return RedirectResponse(f"{settings.FRONTEND_URL}/account?{params}")

    user = db.query(models.User).filter(models.User.id == order.user_id).first()
    if not user:
        logger.warning(f"Billing success: user not found for order {orderId}")
        return RedirectResponse(
            f"{settings.FRONTEND_URL}/?payment=fail&message=사용자를 찾을 수 없습니다"
        )

    # order_id: BILL_{uid}_{code}_{cyc}_{ts}_{rand}
    parts = orderId.split("_")
    tier = _CODE_TIER.get(parts[2], TIER_PRO) if len(parts) >= 6 else TIER_PRO
    is_annual = (parts[3] == "a") if len(parts) >= 6 else (order.amount >= 100_000)

    tier_display = TIER_DISPLAY_NAMES.get(tier, tier)
    order_name = f"BidEasy {tier_display} 자동결제 ({'연간' if is_annual else '월간'})"

    # 1) 빌링키 발급 (sync httpx → threadpool)
    try:
        issued = await run_in_threadpool(issue_billing_key, authKey, customerKey)
    except BillingError as e:
        logger.warning(f"Billing key issue failed: order={orderId} {e.code} {e.message}")
        order.status = "FAILED"
        order.fail_reason = f"빌링키 발급 실패: {e.message}"[:500]
        db.commit()
        return RedirectResponse(
            f"{settings.FRONTEND_URL}/account?payment=fail&message={e.message}"
        )

    # 빌링키·카드정보 저장 (청구 실패해도 카드 등록은 유효 — 재시도 가능)
    user.billing_key = issued["billingKey"]
    user.billing_customer_key = customerKey
    user.billing_card = issued["card_display"]
    user.billing_cycle = "annual" if is_annual else "monthly"
    db.commit()

    # 2) 첫 청구
    try:
        charged = await run_in_threadpool(
            lambda: charge_billing_key(
                billing_key=user.billing_key,
                customer_key=customerKey,
                amount=order.amount,
                order_id=orderId,
                order_name=order_name,
                customer_email=user.email,
                customer_name=user.company_name or user.email,
                idempotency_key=orderId,
            )
        )
    except BillingError as e:
        logger.warning(f"Billing first charge failed: order={orderId} {e.code} {e.message}")
        order.status = "FAILED"
        order.fail_reason = f"첫 결제 실패: {e.message}"[:500]
        user.auto_renew = False
        db.commit()
        return RedirectResponse(
            f"{settings.FRONTEND_URL}/account?payment=fail&message={e.message}"
        )

    # 3) 티어 적용 + 자동갱신 ON
    days = _apply_subscription_after_charge(user, tier, is_annual, extend_from_existing=False)
    user.auto_renew = True
    # 결제 완료 → 진행 중이던 체험 종료 (유료 전환). trial_started_at 은 유지해
    # 재체험 불가는 그대로 두고, trial_expires_at 만 만료시켜 is_trial=False 로.
    user.trial_expires_at = datetime.now(timezone.utc)
    order.status = "CONFIRMED"
    order.payment_key = charged["paymentKey"]
    order.method = charged["method"]
    order.confirmed_at = datetime.now(timezone.utc)
    db.commit()

    logger.info(
        f"Billing first charge confirmed: order={orderId}, user={user.id}, "
        f"tier={tier}, days={days}, card={user.billing_card}"
    )
    log_event(
        "billing_first_charge",
        user_id=user.id,
        tier=tier,
        cycle=user.billing_cycle,
        amount=order.amount,
    )
    params = urlencode({"payment": "success", "amount": str(order.amount), "type": "billing"})
    return RedirectResponse(f"{settings.FRONTEND_URL}/account?{params}")


@router.get("/billing/fail")
async def billing_fail(
    code: str = Query(default=""),
    message: str = Query(default="자동결제 등록이 취소되었습니다"),
    orderId: str = Query(default=""),
    db: Session = Depends(get_db),
):
    """빌링 인증 실패/취소 콜백."""
    if orderId:
        order = (
            db.query(models.PaymentOrder)
            .filter(models.PaymentOrder.order_id == orderId)
            .first()
        )
        if order and order.status == "PENDING":
            order.status = "FAILED"
            order.fail_reason = f"{code}: {message}"[:500]
            db.commit()
    logger.info(f"Billing auth failed/cancelled: order={orderId} code={code} msg={message}")
    return RedirectResponse(
        f"{settings.FRONTEND_URL}/account?payment=fail&message={message}"
    )


@router.get("/billing")
def get_billing_info(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """현재 사용자의 자동결제(빌링) 상태."""
    has_key = bool(current_user.billing_key)
    return {
        "registered": has_key,
        "auto_renew": bool(current_user.auto_renew),
        "card": current_user.billing_card or "",
        "billing_cycle": current_user.billing_cycle,
        "tier": current_user.tier or TIER_FREE,
        "next_charge_at": current_user.subscription_expires_at.isoformat()
        if (current_user.auto_renew and current_user.subscription_expires_at)
        else None,
        "provider": current_user.billing_provider,
    }


@router.get("/provider")
def get_payment_provider():
    """현재 정기결제 PG (프론트가 결제 흐름 분기용). 공개."""
    return {
        "provider": settings.PAYMENT_PROVIDER,
        "payple_host": settings.payple_host,
        "payple_client_key": settings.PAYPLE_CLIENT_KEY,
        "payple_is_test": settings.PAYPLE_IS_TEST,
    }


# ─── 페이플(Payple) 정기결제 Endpoints ───
#
# 토스 빌링 심사(1~2개월) 대기 중 페이플(심사 7일~2주)로 먼저 출시 가능.
# 흐름: prepare(주문생성) → [프론트 PaypleCpayAuthCheck 카드등록+첫청구]
#       → callback(빌링키 저장+티어적용). 자동갱신은 Celery 가 PG 구분해 청구.

@router.post("/payple/prepare")
def payple_prepare(
    request: SubscribeRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """페이플 정기결제 등록 준비 — 주문 생성 + 프론트 SDK 파라미터 반환."""
    if request.tier not in (TIER_PRO, TIER_PRO_PLUS):
        raise HTTPException(status_code=400, detail="유효하지 않은 구독 티어입니다")
    if request.billing_cycle not in ("monthly", "annual"):
        raise HTTPException(status_code=400, detail="유효하지 않은 결제 주기입니다")

    is_annual = request.billing_cycle == "annual"
    original_amount = (ANNUAL_PRICES if is_annual else MONTHLY_PRICES)[request.tier]

    from app.schemas.subscription import (
        is_winback_eligible,
        calculate_winback_discount,
        WINBACK_REASON_CODE,
    )
    amount = original_amount
    discount_amount = None
    discount_reason = None
    if not is_annual and is_winback_eligible(current_user, db):
        discount_amount = calculate_winback_discount(original_amount)
        amount = original_amount - discount_amount
        discount_reason = WINBACK_REASON_CODE

    now = datetime.now(timezone.utc)
    ts = int(now.timestamp())
    rand = secrets.token_hex(4)
    cyc = "a" if is_annual else "m"
    order_id = f"PYP_{current_user.id}_{_TIER_CODE[request.tier]}_{cyc}_{ts}_{rand}"

    order = models.PaymentOrder(
        user_id=current_user.id, order_id=order_id, amount=amount, status="PENDING",
        discount_amount=discount_amount, discount_reason=discount_reason,
    )
    db.add(order)
    db.commit()

    tier_display = TIER_DISPLAY_NAMES.get(request.tier, request.tier)
    goods = f"BidEasy {tier_display} 자동결제 ({'연간' if is_annual else '월간'})"
    logger.info(f"Payple prepare: order={order_id} user={current_user.id} amount={amount}")

    return {
        "client_key": settings.PAYPLE_CLIENT_KEY,
        "host": settings.payple_host,
        "is_test": settings.PAYPLE_IS_TEST,
        "order_id": order_id,
        "goods": goods,
        "amount": amount,
        "payer_no": str(current_user.id),
        "payer_name": current_user.company_name or current_user.email or "BidEasy User",
        "payer_email": current_user.email or "",
        "rst_url": f"{settings.BACKEND_URL}/api/v1/payments/payple/callback",
        "tier": request.tier,
        "billing_cycle": request.billing_cycle,
    }


@router.post("/payple/callback")
async def payple_callback(request: Request, db: Session = Depends(get_db)):
    """페이플 카드등록(CERT) 콜백 → 빌링키 저장 + 첫 청구(PAYM) 실행 → 성공 시 티어 적용.

    CERT 는 카드만 등록(100원 인증 후 취소)하고 실제 금액은 청구하지 않으므로,
    여기서 빌링키로 첫 청구를 직접 실행해야 매출이 발생한다(청구 성공 시에만 구독 적용).
    """
    form = dict(await request.form())
    rst = str(form.get("PCD_PAY_RST", "")).lower()
    oid = form.get("PCD_PAY_OID", "")
    payer_id = form.get("PCD_PAYER_ID", "")

    order = db.query(models.PaymentOrder).filter(models.PaymentOrder.order_id == oid).first()
    if not order:
        logger.warning(f"Payple callback: order not found: {oid}")
        return RedirectResponse(f"{settings.FRONTEND_URL}/account?payment=fail&message=주문을 찾을 수 없습니다", status_code=303)

    # 멱등성: 이미 확정된 주문이면 재청구 없이 성공 응답 (콜백 재전송/중복 POST 방어)
    if order.status == "CONFIRMED":
        logger.info(f"Payple callback: order already confirmed, skip recharge: {oid}")
        params = urlencode({"payment": "success", "amount": str(order.amount), "type": "billing"})
        return RedirectResponse(f"{settings.FRONTEND_URL}/account?{params}", status_code=303)

    # 콜백 진위 검증: 콜백에 가맹점 식별자(CST_ID)가 있으면 자사 값과 일치해야 함 (위조 콜백 차단)
    cb_cst_id = form.get("PCD_CST_ID")
    if cb_cst_id and cb_cst_id != settings.PAYPLE_CST_ID:
        logger.warning(f"Payple callback: CST_ID mismatch oid={oid} got={cb_cst_id!r}")
        order.status = "FAILED"
        order.fail_reason = "콜백 검증 실패(CST_ID 불일치)"
        db.commit()
        return RedirectResponse(f"{settings.FRONTEND_URL}/account?payment=fail&message=결제 검증에 실패했습니다", status_code=303)

    # 금액 변조 방어: 콜백이 결제총액을 보고한 경우 서버 주문금액과 대조
    cb_total = form.get("PCD_PAY_TOTAL")
    if cb_total:
        try:
            if int(str(cb_total).replace(",", "")) != int(order.amount):
                logger.warning(f"Payple callback: amount mismatch oid={oid} cb={cb_total} order={order.amount}")
                order.status = "FAILED"
                order.fail_reason = "콜백 검증 실패(금액 불일치)"
                db.commit()
                return RedirectResponse(f"{settings.FRONTEND_URL}/account?payment=fail&message=결제 금액 검증에 실패했습니다", status_code=303)
        except (ValueError, TypeError):
            pass

    if rst != "success" or not payer_id:
        order.status = "FAILED"
        order.fail_reason = (form.get("PCD_PAY_MSG") or "카드 등록 실패")[:500]
        db.commit()
        msg = form.get("PCD_PAY_MSG") or "결제에 실패했습니다"
        return RedirectResponse(f"{settings.FRONTEND_URL}/account?payment=fail&message={msg}", status_code=303)

    user = db.query(models.User).filter(models.User.id == order.user_id).first()
    if not user:
        return RedirectResponse(f"{settings.FRONTEND_URL}/account?payment=fail&message=사용자를 찾을 수 없습니다", status_code=303)

    # order_id: PYP_{uid}_{code}_{cyc}_{ts}_{rand}
    parts = oid.split("_")
    tier = _CODE_TIER.get(parts[2], TIER_PRO) if len(parts) >= 6 else TIER_PRO
    is_annual = (parts[3] == "a") if len(parts) >= 6 else (order.amount >= 100_000)

    # ── CERT 콜백 = 카드 등록(빌링키 발급) 성공이지 '결제' 성공이 아님. ──
    # 실제 첫 청구는 빌링키로 서버에서 직접(PAYM). 갱신 태스크(billing_tasks)와 동일 경로.
    charge_oid = f"PYPC_{user.id}_{int(datetime.now(timezone.utc).timestamp())}_{secrets.token_hex(3)}"
    goods = f"BidEasy {TIER_DISPLAY_NAMES.get(tier, tier)} 자동결제 ({'연간' if is_annual else '월간'})"
    try:
        charge = payple_svc.charge_billing(
            payer_id=payer_id, amount=int(order.amount), oid=charge_oid, goods=goods,
            payer_name=form.get("PCD_PAYER_NAME") or user.company_name or user.email,
            payer_email=form.get("PCD_PAYER_EMAIL") or user.email or "",
        )
    except payple_svc.PaypleError as e:
        # 첫 청구 실패 → 빌링키를 저장하지 않음.
        # (미검증 payer_id 가 user.billing_key 에 남아 다음 Celery 갱신 때
        #  타인 카드로 청구되는 오염을 방지. 빌링키는 청구 성공 시에만 저장한다.)
        order.status = "FAILED"
        order.fail_reason = (getattr(e, "message", "") or "첫 청구 실패")[:500]
        db.commit()
        logger.warning(
            f"Payple first charge FAILED: reg_oid={oid} user={user.id} "
            f"code={getattr(e, 'code', '')} msg={getattr(e, 'message', '')}"
        )
        msg = getattr(e, "message", "") or "첫 결제에 실패했습니다"
        return RedirectResponse(f"{settings.FRONTEND_URL}/account?payment=fail&message={msg}", status_code=303)

    # ── 첫 청구 성공 → 빌링키 저장 + 구독 적용 + CONFIRMED ──
    user.billing_key = payer_id
    user.billing_provider = "payple"
    user.billing_card = payple_svc.card_display(form)
    user.billing_cycle = "annual" if is_annual else "monthly"
    days = _apply_subscription_after_charge(user, tier, is_annual, extend_from_existing=False)
    user.auto_renew = True
    user.trial_expires_at = datetime.now(timezone.utc)  # 결제 → 체험 종료
    order.status = "CONFIRMED"
    # 실제 청구 OID 를 거래 참조로 저장 (빌링키는 user.billing_key 에 보관).
    order.payment_key = charge.get("PCD_PAY_OID") or charge_oid
    order.method = "card"
    order.confirmed_at = datetime.now(timezone.utc)
    db.commit()

    logger.info(f"Payple first charge confirmed: order={oid} user={user.id} tier={tier} days={days}")
    log_event("payple_first_charge", user_id=user.id, tier=tier, cycle=user.billing_cycle, amount=order.amount)
    params = urlencode({"payment": "success", "amount": str(order.amount), "type": "billing"})
    # 303 See Other: POST 콜백 → GET /account 로 전환 (307 이면 메서드 유지돼 정적 /account 에 POST → nginx 405)
    return RedirectResponse(f"{settings.FRONTEND_URL}/account?{params}", status_code=303)
