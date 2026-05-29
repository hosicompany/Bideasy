"""
첫 달 50% 할인 (Win-back) 자격 + 자동 적용 테스트.

- 활성 Trial 사용자 → 자격 있음
- Trial 만료 7일 이내 → 자격 있음
- Trial 만료 8일 후 → 자격 없음
- 이미 결제한 사용자 → 자격 없음
- Trial 시작 안 함 → 자격 없음
- 월간 결제 + 자격 → amount 50% 할인 + discount_amount/reason 기록
- 연간 결제 + 자격 → 정가 (win-back 미적용)
- 자격 사용 후 결제 완료 → 두 번째 결제는 자격 없음 (첫 결제만)
- /payments/subscription 응답 winback_eligible 필드 확인
"""
from datetime import datetime, timedelta, timezone

from app.db import models
from app.schemas.subscription import (
    is_winback_eligible,
    winback_expires_at,
    calculate_winback_discount,
    activate_trial,
    WINBACK_DISCOUNT_PCT,
    WINBACK_GRACE_DAYS,
    WINBACK_REASON_CODE,
)
from app.core.security import create_access_token


# ── 헬퍼 ─────────────────────────────────────────────────────

def _make_user(db, email, **kwargs):
    user = models.User(email=email, hashed_password="x", **kwargs)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _auth(client, db, email, **kwargs):
    user = _make_user(db, email, **kwargs)
    token = create_access_token({"sub": str(user.id)})
    client.headers["Authorization"] = f"Bearer {token}"
    return client, user


# ── is_winback_eligible 단위 ─────────────────────────────────

def test_winback_active_trial(db_session):
    """활성 Trial 사용자는 자격 있음."""
    user = _make_user(db_session, "wb-1@test.com")
    activate_trial(user)
    db_session.commit()
    assert is_winback_eligible(user, db_session) is True


def test_winback_just_expired(db_session):
    """Trial 만료 직후 (1시간 전) → 자격 있음 (grace 안)."""
    user = _make_user(db_session, "wb-2@test.com")
    user.trial_started_at = datetime.now(timezone.utc) - timedelta(days=14, hours=1)
    user.trial_expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
    db_session.commit()
    assert is_winback_eligible(user, db_session) is True


def test_winback_within_grace(db_session):
    """Trial 만료 후 grace 내 (예: 5일) → 자격 있음."""
    user = _make_user(db_session, "wb-3@test.com")
    user.trial_started_at = datetime.now(timezone.utc) - timedelta(days=19)
    user.trial_expires_at = datetime.now(timezone.utc) - timedelta(days=5)
    db_session.commit()
    assert is_winback_eligible(user, db_session) is True


def test_winback_after_grace(db_session):
    """Trial 만료 후 grace 초과 (8일) → 자격 없음."""
    user = _make_user(db_session, "wb-4@test.com")
    user.trial_started_at = datetime.now(timezone.utc) - timedelta(days=22)
    user.trial_expires_at = datetime.now(timezone.utc) - timedelta(days=8)
    db_session.commit()
    assert is_winback_eligible(user, db_session) is False


def test_winback_no_trial(db_session):
    """Trial 시작 안 함 → 자격 없음."""
    user = _make_user(db_session, "wb-5@test.com")
    assert is_winback_eligible(user, db_session) is False


def test_winback_already_paid(db_session):
    """이미 CONFIRMED 결제 1건 있으면 → 자격 없음 (첫 결제만)."""
    user = _make_user(db_session, "wb-6@test.com")
    activate_trial(user)
    db_session.commit()
    # 과거 결제 추가
    db_session.add(
        models.PaymentOrder(
            user_id=user.id, order_id="OLD_SUB_1", amount=14900,
            status="CONFIRMED",
            confirmed_at=datetime.now(timezone.utc) - timedelta(days=10),
        )
    )
    db_session.commit()
    assert is_winback_eligible(user, db_session) is False


def test_winback_pending_payment_does_not_disqualify(db_session):
    """PENDING/FAILED 결제는 첫 결제 자격 박탈 X."""
    user = _make_user(db_session, "wb-7@test.com")
    activate_trial(user)
    db_session.add_all([
        models.PaymentOrder(user_id=user.id, order_id="P1", amount=14900, status="PENDING"),
        models.PaymentOrder(user_id=user.id, order_id="F1", amount=14900, status="FAILED"),
    ])
    db_session.commit()
    assert is_winback_eligible(user, db_session) is True


# ── 계산 함수 ───────────────────────────────────────────────

def test_calculate_winback_discount():
    assert calculate_winback_discount(14_900) == 7_450
    assert calculate_winback_discount(29_900) == 14_950
    assert calculate_winback_discount(0) == 0


def test_winback_expires_at(db_session):
    user = _make_user(db_session, "wb-exp@test.com")
    activate_trial(user)
    exp = winback_expires_at(user)
    assert exp is not None
    trial_exp = user.trial_expires_at
    if trial_exp.tzinfo is None:
        trial_exp = trial_exp.replace(tzinfo=timezone.utc)
    delta = exp - trial_exp
    assert delta.days == WINBACK_GRACE_DAYS


# ── E2E /payments/subscribe ─────────────────────────────────

def test_subscribe_applies_winback_for_monthly(client, db_session):
    """자격 있는 사용자 + 월간 → 7,450원 청구 + discount 기록."""
    client, user = _auth(client, db_session, "sub-wb-1@test.com")
    activate_trial(user)
    db_session.commit()

    resp = client.post(
        "/api/v1/payments/subscribe",
        json={"tier": "pro", "billing_cycle": "monthly"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["amount"] == 7_450  # 14,900 / 2

    # DB 기록 확인
    order = (
        db_session.query(models.PaymentOrder)
        .filter(models.PaymentOrder.order_id == data["order_id"])
        .first()
    )
    assert order.discount_amount == 7_450
    assert order.discount_reason == WINBACK_REASON_CODE


def test_subscribe_no_winback_for_annual(client, db_session):
    """자격 있어도 연간은 win-back 미적용 (이미 20% 할인)."""
    client, user = _auth(client, db_session, "sub-wb-2@test.com")
    activate_trial(user)
    db_session.commit()

    resp = client.post(
        "/api/v1/payments/subscribe",
        json={"tier": "pro", "billing_cycle": "annual"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["amount"] == 140_000  # 정가, win-back 미적용

    order = (
        db_session.query(models.PaymentOrder)
        .filter(models.PaymentOrder.order_id == data["order_id"])
        .first()
    )
    assert order.discount_amount is None
    assert order.discount_reason is None


def test_subscribe_no_winback_if_not_eligible(client, db_session):
    """자격 없는 사용자(Trial 8일+ 경과) 월간 → 정가 14,900."""
    client, user = _auth(client, db_session, "sub-wb-3@test.com")
    user.trial_started_at = datetime.now(timezone.utc) - timedelta(days=30)
    user.trial_expires_at = datetime.now(timezone.utc) - timedelta(days=16)
    db_session.commit()

    resp = client.post(
        "/api/v1/payments/subscribe",
        json={"tier": "pro", "billing_cycle": "monthly"},
    )
    assert resp.status_code == 200
    assert resp.json()["amount"] == 14_900


def test_subscribe_pro_plus_winback(client, db_session):
    """Pro+ 월간도 자격 있으면 50% 할인."""
    client, user = _auth(client, db_session, "sub-wb-4@test.com")
    activate_trial(user)
    db_session.commit()

    resp = client.post(
        "/api/v1/payments/subscribe",
        json={"tier": "pro_plus", "billing_cycle": "monthly"},
    )
    assert resp.status_code == 200
    assert resp.json()["amount"] == 14_950  # 29,900 / 2


# ── E2E /payments/subscription 응답 ──────────────────────────

def test_subscription_endpoint_exposes_winback_eligible(client, db_session):
    client, user = _auth(client, db_session, "info-wb-1@test.com")
    activate_trial(user)
    db_session.commit()

    resp = client.get("/api/v1/payments/subscription")
    assert resp.status_code == 200
    data = resp.json()
    assert data["winback_eligible"] is True
    assert data["winback_discount_pct"] == WINBACK_DISCOUNT_PCT
    assert data["winback_expires_at"] is not None


def test_subscription_endpoint_winback_false_after_grace(client, db_session):
    client, user = _auth(client, db_session, "info-wb-2@test.com")
    user.trial_started_at = datetime.now(timezone.utc) - timedelta(days=22)
    user.trial_expires_at = datetime.now(timezone.utc) - timedelta(days=8)
    db_session.commit()

    resp = client.get("/api/v1/payments/subscription")
    assert resp.status_code == 200
    data = resp.json()
    assert data["winback_eligible"] is False
    assert data["winback_discount_pct"] == 0
    assert data["winback_expires_at"] is None
