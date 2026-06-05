"""
자동결제(빌링) 갱신 Celery 태스크
=====================================
auto_renew=True + billing_key 보유 사용자의 구독을 만료 직전 자동청구로 갱신.

스케줄 (celery_app.py beat_schedule):
- 매일 03:00 KST: billing.charge_due_subscriptions
  → 만료 임박(D-1 ~ 만료) 사용자 식별 → 빌링키로 청구 → 만료일 연장

실패 처리:
- 청구 실패 시 그 날은 실패로 기록하고 다음날 재시도 (구독은 만료일까지 유지).
- 만료 후 BILLING_RETRY_GRACE_DAYS(3일) 동안 계속 실패하면 자동갱신 해지 + Free 강등.

중복청구 방지:
- idempotency_key = renew-{uid}-{만료일자} → 같은 갱신 주기에는 토스가 1회만 청구.
"""

from datetime import datetime, timedelta, timezone

from app.core.celery_app import celery_app
from app.core.logging import get_logger
from app.core.analytics import log_event
from app.db import models
from app.db.session import SessionLocal
from app.services.billing import charge_billing_key, BillingError
from app.schemas.subscription import (
    TIER_FREE,
    TIER_PRO,
    TIER_PRO_PLUS,
    TIER_DISPLAY_NAMES,
)

logger = get_logger(__name__)

import secrets  # noqa: E402

# 만료 며칠 전부터 갱신 청구를 시도할지 (공백 없는 연속 구독 보장)
BILLING_RENEW_LEAD_DAYS = 1
# 만료 후 며칠까지 재시도하다 포기(해지+강등)할지
BILLING_RETRY_GRACE_DAYS = 3

_TIER_CODE = {TIER_PRO: "P", TIER_PRO_PLUS: "PP"}

_NOTI = {
    "BILLING_RENEWED": (
        "구독이 자동 갱신되었어요 ✅",
        "{tier} 구독이 갱신되었습니다. 다음 결제일: {next_date}.",
    ),
    "BILLING_FAILED_RETRY": (
        "자동결제에 실패했어요 ⚠️",
        "등록된 카드로 결제가 되지 않았습니다. 카드를 확인해 주세요. 내일 다시 시도합니다.",
    ),
    "BILLING_CANCELLED": (
        "자동결제가 해지되었어요",
        "결제 실패가 반복되어 자동 갱신을 해지했습니다. 계속 이용하시려면 다시 결제해 주세요.",
    ),
}


def _aware(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _notify(db, user_id: int, noti_type: str, **fmt) -> None:
    title, body = _NOTI[noti_type]
    noti = models.Notification(
        user_id=user_id,
        title=title.format(**fmt),
        body=body.format(**fmt),
        noti_type=noti_type,
        data_json={"billing_event": noti_type},
        is_read=0,
    )
    db.add(noti)


@celery_app.task(name="billing.charge_due_subscriptions")
def charge_due_subscriptions(now_iso: str = "") -> dict:
    """만료 임박 자동결제 사용자 갱신 청구.

    now_iso: 테스트용 기준시각 override (ISO8601). 비우면 현재 UTC.
    """
    db = SessionLocal()
    results = {"charged": 0, "failed": 0, "cancelled": 0, "skipped": 0}
    try:
        now = datetime.fromisoformat(now_iso) if now_iso else datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        due_cutoff = now + timedelta(days=BILLING_RENEW_LEAD_DAYS)

        # 자동갱신 대상: auto_renew + 빌링키 보유 + 만료가 due_cutoff 이내
        candidates = (
            db.query(models.User)
            .filter(
                models.User.auto_renew.is_(True),
                models.User.billing_key.isnot(None),
                models.User.subscription_expires_at.isnot(None),
                models.User.subscription_expires_at <= due_cutoff,
            )
            .all()
        )

        for u in candidates:
            tier = u.tier if u.tier in (TIER_PRO, TIER_PRO_PLUS) else TIER_PRO
            is_annual = (u.billing_cycle == "annual")
            amount = _renew_amount(tier, is_annual)
            expires = _aware(u.subscription_expires_at)

            ts = int(now.timestamp())
            rand = secrets.token_hex(4)
            cyc = "a" if is_annual else "m"
            order_id = f"BILLR_{u.id}_{_TIER_CODE[tier]}_{cyc}_{ts}_{rand}"
            tier_display = TIER_DISPLAY_NAMES.get(tier, tier)
            order_name = f"BidEasy {tier_display} 자동결제 ({'연간' if is_annual else '월간'})"

            order = models.PaymentOrder(
                user_id=u.id, order_id=order_id, amount=amount, status="PENDING"
            )
            db.add(order)
            db.commit()

            try:
                charged = charge_billing_key(
                    billing_key=u.billing_key,
                    customer_key=u.billing_customer_key,
                    amount=amount,
                    order_id=order_id,
                    order_name=order_name,
                    customer_email=u.email,
                    customer_name=u.company_name or u.email,
                    # 같은 갱신 주기(만료일자) 중복청구 방지
                    idempotency_key=f"renew-{u.id}-{expires.date().isoformat()}",
                )
            except BillingError as e:
                order.status = "FAILED"
                order.fail_reason = f"자동갱신 실패: {e.message}"[:500]
                # 만료 후 grace 경과까지 계속 실패 → 해지 + 강등
                if now > expires + timedelta(days=BILLING_RETRY_GRACE_DAYS):
                    u.auto_renew = False
                    u.tier = TIER_FREE
                    _notify(db, u.id, "BILLING_CANCELLED")
                    results["cancelled"] += 1
                    log_event("billing_renew_cancelled", user_id=u.id, tier=tier, reason=e.code)
                else:
                    _notify(db, u.id, "BILLING_FAILED_RETRY")
                    results["failed"] += 1
                    log_event("billing_renew_failed", user_id=u.id, tier=tier, reason=e.code)
                db.commit()
                continue

            # 성공 → 만료일 연장 (남은 기간에 이어붙임)
            days = 365 if is_annual else 30
            start = expires if expires > now else now
            u.subscription_expires_at = start + timedelta(days=days)
            u.tier = tier
            order.status = "CONFIRMED"
            order.payment_key = charged["paymentKey"]
            order.method = charged["method"]
            order.confirmed_at = now
            _notify(
                db, u.id, "BILLING_RENEWED",
                tier=tier_display,
                next_date=u.subscription_expires_at.date().isoformat(),
            )
            db.commit()
            results["charged"] += 1
            log_event("billing_renewed", user_id=u.id, tier=tier, cycle=u.billing_cycle, amount=amount)

        logger.info(f"[billing.charge_due_subscriptions] {results}")
        return results
    except Exception as e:
        db.rollback()
        logger.error(f"[billing.charge_due_subscriptions] error: {e}", exc_info=True)
        return {"error": str(e), **results}
    finally:
        db.close()


def _renew_amount(tier: str, is_annual: bool) -> int:
    """갱신 청구 정가 (win-back 등 1회성 할인은 갱신에 적용하지 않음)."""
    from app.schemas.subscription import MONTHLY_PRICES, ANNUAL_PRICES
    return (ANNUAL_PRICES if is_annual else MONTHLY_PRICES)[tier]
