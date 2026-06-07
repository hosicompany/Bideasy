"""자동결제(빌링) E2E 테스트.

토스 빌링 API(issue_billing_key / charge_billing_key)는 모킹하여
엔드포인트·Celery 태스크의 오케스트레이션 로직을 검증한다.
  prepare → success(빌링키 발급+첫청구+티어적용) → billing 조회 → 해지
  + Celery 자동갱신(charge_due_subscriptions)
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.db import models
from app.db.session import get_db
from app.services.billing import BillingError
from main import app


# 공유 fixture(free_client=test-free@test.com)를 오염시키지 않도록 빌링 전용 사용자 사용.
_BILLING_EMAIL = "test-billing@test.com"


@pytest.fixture
def billing_client(db_session):
    """빌링 전용 사용자(Free 시작)로 인증된 TestClient — 다른 테스트와 격리."""
    from app.core.security import create_access_token

    user = db_session.query(models.User).filter(models.User.email == _BILLING_EMAIL).first()
    if not user:
        user = models.User(email=_BILLING_EMAIL, hashed_password="x", tier="free")
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)
    else:
        # 이전 테스트 잔여 상태 초기화 (격리)
        user.tier = "free"
        user.auto_renew = False
        user.billing_key = None
        user.billing_card = None
        user.billing_cycle = None
        user.subscription_expires_at = None
        user.trial_started_at = None
        user.trial_expires_at = None
        db_session.commit()

    token = create_access_token({"sub": str(user.id)})

    def _override():
        yield db_session

    app.dependency_overrides[get_db] = _override
    with TestClient(app) as c:
        c.headers["Authorization"] = f"Bearer {token}"
        yield c
    app.dependency_overrides.clear()


# ─── Toss 빌링 API 모킹 헬퍼 ─────────────────────────────

def _fake_issue(auth_key, customer_key):
    return {
        "billingKey": "bk_test_" + customer_key[-6:],
        "card_display": "신한 ****1234",
        "method": "카드",
        "raw": {"billingKey": "bk_test", "card": {"number": "123456******1234"}},
    }


def _fake_charge(**kwargs):
    return {
        "paymentKey": "pk_test_" + kwargs.get("order_id", "x")[-6:],
        "status": "DONE",
        "method": "카드",
        "raw": {"status": "DONE", "totalAmount": kwargs.get("amount")},
    }


def _fake_charge_fail(**kwargs):
    raise BillingError("카드 한도 초과", code="EXCEED_MAX_AMOUNT", status_code=403)


def _get_billing_user(db):
    return db.query(models.User).filter(models.User.email == _BILLING_EMAIL).first()


# ─── prepare ─────────────────────────────────────────────

def test_billing_prepare_creates_order_and_customer_key(billing_client, db_session):
    resp = billing_client.post(
        "/api/v1/payments/billing/prepare",
        json={"tier": "pro", "billing_cycle": "monthly"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["order_id"].startswith("BILL_")
    assert data["customer_key"]
    assert data["amount"] in (14_900, 7_450)  # 정가 또는 win-back 50%
    assert data["tier"] == "pro"
    assert data["toss_client_key"] is not None

    # customerKey 가 사용자에 저장됨 (재사용)
    user = _get_billing_user(db_session)
    assert user.billing_customer_key == data["customer_key"]

    # PENDING 주문 생성됨
    order = (
        db_session.query(models.PaymentOrder)
        .filter(models.PaymentOrder.order_id == data["order_id"])
        .first()
    )
    assert order is not None
    assert order.status == "PENDING"


def test_billing_prepare_rejects_invalid_tier(billing_client):
    resp = billing_client.post(
        "/api/v1/payments/billing/prepare",
        json={"tier": "free", "billing_cycle": "monthly"},
    )
    assert resp.status_code == 400


# ─── success (발급 + 첫 청구 + 티어 적용) ────────────────

def test_billing_success_issues_charges_and_upgrades(billing_client, db_session):
    prep = billing_client.post(
        "/api/v1/payments/billing/prepare",
        json={"tier": "pro", "billing_cycle": "monthly"},
    ).json()

    with patch("app.api.v1.endpoints.payments.issue_billing_key", _fake_issue), \
         patch("app.api.v1.endpoints.payments.charge_billing_key", _fake_charge):
        resp = billing_client.get(
            "/api/v1/payments/billing/success",
            params={"customerKey": prep["customer_key"], "authKey": "ak_test", "orderId": prep["order_id"]},
            follow_redirects=False,
        )

    assert resp.status_code in (302, 307)
    assert "payment=success" in resp.headers["location"]
    assert "/account" in resp.headers["location"]

    db_session.expire_all()
    user = _get_billing_user(db_session)
    assert user.tier == "pro"
    assert user.auto_renew is True
    assert user.billing_key
    assert user.billing_card == "신한 ****1234"
    assert user.billing_cycle == "monthly"
    assert user.subscription_expires_at is not None
    # 만료일 ≈ 30일 후
    exp = user.subscription_expires_at
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    delta_days = (exp - datetime.now(timezone.utc)).days
    assert 28 <= delta_days <= 31

    order = (
        db_session.query(models.PaymentOrder)
        .filter(models.PaymentOrder.order_id == prep["order_id"])
        .first()
    )
    assert order.status == "CONFIRMED"
    assert order.payment_key


def test_billing_success_ends_active_trial(billing_client, db_session):
    """체험 중 결제 → 체험 종료(is_trial=False) + 유료 Pro 전환."""
    user = _get_billing_user(db_session)
    now = datetime.now(timezone.utc)
    user.trial_started_at = now - timedelta(days=1)
    user.trial_expires_at = now + timedelta(days=13)  # 체험 활성
    db_session.commit()

    prep = billing_client.post(
        "/api/v1/payments/billing/prepare",
        json={"tier": "pro", "billing_cycle": "monthly"},
    ).json()
    with patch("app.api.v1.endpoints.payments.issue_billing_key", _fake_issue), \
         patch("app.api.v1.endpoints.payments.charge_billing_key", _fake_charge):
        billing_client.get(
            "/api/v1/payments/billing/success",
            params={"customerKey": prep["customer_key"], "authKey": "ak", "orderId": prep["order_id"]},
            follow_redirects=False,
        )

    # /subscription 이 체험이 아닌 유료 활성으로 보고해야 함
    sub = billing_client.get("/api/v1/payments/subscription").json()
    assert sub["is_trial"] is False, "결제 후에도 체험으로 표시되면 안 됨"
    assert sub["tier"] == "pro"
    assert sub["is_active"] is True


def test_billing_success_charge_failure_no_autorenew(billing_client, db_session):
    prep = billing_client.post(
        "/api/v1/payments/billing/prepare",
        json={"tier": "pro", "billing_cycle": "monthly"},
    ).json()

    with patch("app.api.v1.endpoints.payments.issue_billing_key", _fake_issue), \
         patch("app.api.v1.endpoints.payments.charge_billing_key", _fake_charge_fail):
        resp = billing_client.get(
            "/api/v1/payments/billing/success",
            params={"customerKey": prep["customer_key"], "authKey": "ak_test", "orderId": prep["order_id"]},
            follow_redirects=False,
        )

    assert resp.status_code in (302, 307)
    assert "payment=fail" in resp.headers["location"]

    db_session.expire_all()
    user = _get_billing_user(db_session)
    # 카드(빌링키)는 등록됐지만 첫 청구 실패 → 자동갱신 OFF, 티어 미상승
    assert user.billing_key  # 빌링키는 저장됨 (재시도 가능)
    assert user.auto_renew is False

    order = (
        db_session.query(models.PaymentOrder)
        .filter(models.PaymentOrder.order_id == prep["order_id"])
        .first()
    )
    assert order.status == "FAILED"


# ─── 회귀: naive 만료일 + 유료 tier 에서 /subscription 500 방지 ───
# prod(PostgreSQL)는 DateTime 을 naive 로 반환 → aware now 와 비교 시 TypeError.
# SQLite 는 보통 aware 로 round-trip 되므로, 여기선 명시적 naive 값을 넣어 재현한다.

def test_subscription_handles_naive_expires_at(billing_client, db_session):
    user = _get_billing_user(db_session)
    user.tier = "pro"
    user.subscription_expires_at = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=10)
    db_session.commit()

    resp = billing_client.get("/api/v1/payments/subscription")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["tier"] == "pro"
    assert data["is_active"] is True


# ─── billing 조회 + 해지 ─────────────────────────────────

def test_get_billing_and_cancel(billing_client, db_session):
    prep = billing_client.post(
        "/api/v1/payments/billing/prepare",
        json={"tier": "pro", "billing_cycle": "monthly"},
    ).json()
    with patch("app.api.v1.endpoints.payments.issue_billing_key", _fake_issue), \
         patch("app.api.v1.endpoints.payments.charge_billing_key", _fake_charge):
        billing_client.get(
            "/api/v1/payments/billing/success",
            params={"customerKey": prep["customer_key"], "authKey": "ak", "orderId": prep["order_id"]},
            follow_redirects=False,
        )

    # billing 조회
    info = billing_client.get("/api/v1/payments/billing").json()
    assert info["registered"] is True
    assert info["auto_renew"] is True
    assert info["card"] == "신한 ****1234"
    assert info["next_charge_at"] is not None

    # 해지 → auto_renew=False, 티어·만료일 유지
    db_session.expire_all()
    user_before = _get_billing_user(db_session)
    exp_before = user_before.subscription_expires_at
    tier_before = user_before.tier

    cancel = billing_client.post("/api/v1/payments/subscribe/cancel")
    assert cancel.status_code == 200

    db_session.expire_all()
    user_after = _get_billing_user(db_session)
    assert user_after.auto_renew is False
    assert user_after.tier == tier_before  # 만료일까지 유지
    assert user_after.subscription_expires_at == exp_before

    info2 = billing_client.get("/api/v1/payments/billing").json()
    assert info2["auto_renew"] is False
    assert info2["next_charge_at"] is None


# ─── Celery 자동 갱신 ────────────────────────────────────

class _SessionWrapper:
    def __init__(self, real):
        self._real = real

    def __getattr__(self, name):
        if name == "close":
            return lambda: None
        return getattr(self._real, name)


def _patch_session(db_session):
    return patch("app.tasks.billing_tasks.SessionLocal", lambda: _SessionWrapper(db_session))


def _billing_user(db, email, tier, cycle, expires_in_days, auto_renew=True):
    user = models.User(
        email=email,
        hashed_password="x",
        tier=tier,
        billing_key="bk_existing",
        billing_customer_key="cust_existing",
        billing_card="국민 ****5678",
        billing_cycle=cycle,
        auto_renew=auto_renew,
        subscription_expires_at=datetime.now(timezone.utc) + timedelta(days=expires_in_days),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def test_charge_due_subscriptions_renews(db_session):
    from app.tasks.billing_tasks import charge_due_subscriptions

    # 만료가 오늘(due) 인 자동갱신 사용자
    user = _billing_user(db_session, "renew@test.com", "pro", "monthly", expires_in_days=0)
    old_exp = user.subscription_expires_at

    with _patch_session(db_session), \
         patch("app.tasks.billing_tasks.charge_billing_key", _fake_charge):
        result = charge_due_subscriptions()

    assert result["charged"] >= 1
    db_session.expire_all()
    u = db_session.query(models.User).filter(models.User.id == user.id).first()
    # 만료일 연장됨 (+30일)
    new_exp = u.subscription_expires_at
    if new_exp.tzinfo is None:
        new_exp = new_exp.replace(tzinfo=timezone.utc)
    if old_exp.tzinfo is None:
        old_exp = old_exp.replace(tzinfo=timezone.utc)
    assert new_exp > old_exp
    assert u.auto_renew is True
    assert u.tier == "pro"

    # CONFIRMED 갱신 주문 생성
    order = (
        db_session.query(models.PaymentOrder)
        .filter(models.PaymentOrder.user_id == user.id, models.PaymentOrder.status == "CONFIRMED")
        .first()
    )
    assert order is not None
    assert order.order_id.startswith("BILLR_")


def test_charge_due_skips_far_future_and_non_autorenew(db_session):
    from app.tasks.billing_tasks import charge_due_subscriptions

    # 만료 한참 남음 → 청구 안 함
    far = _billing_user(db_session, "far@test.com", "pro", "monthly", expires_in_days=20)
    # auto_renew=False → 대상 아님
    off = _billing_user(db_session, "off@test.com", "pro", "monthly", expires_in_days=0, auto_renew=False)

    with _patch_session(db_session), \
         patch("app.tasks.billing_tasks.charge_billing_key", _fake_charge):
        charge_due_subscriptions()

    db_session.expire_all()
    for u in (far, off):
        cnt = (
            db_session.query(models.PaymentOrder)
            .filter(models.PaymentOrder.user_id == u.id)
            .count()
        )
        assert cnt == 0


def test_charge_due_failure_past_grace_cancels(db_session):
    from app.tasks.billing_tasks import charge_due_subscriptions

    # 만료 후 grace(3일) 초과 + 청구 실패 → 자동갱신 해지 + Free 강등
    user = _billing_user(db_session, "grace@test.com", "pro", "monthly", expires_in_days=-5)

    with _patch_session(db_session), \
         patch("app.tasks.billing_tasks.charge_billing_key", _fake_charge_fail):
        result = charge_due_subscriptions()

    assert result["cancelled"] >= 1
    db_session.expire_all()
    u = db_session.query(models.User).filter(models.User.id == user.id).first()
    assert u.auto_renew is False
    assert u.tier == "free"
