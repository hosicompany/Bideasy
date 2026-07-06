"""페이플(Payple) 정기결제 E2E 테스트.

페이플 HTTP(파트너인증/청구)는 모킹하여 엔드포인트·Celery 오케스트레이션을 검증한다.
  prepare(주문생성) → callback(빌링키 저장+첫청구+티어적용) → 자동갱신(charge_due_subscriptions, payple)

페이플 결제창(PaypleCpayAuthCheck)은 브라우저 SDK 라 테스트 대상 아님 —
서버가 받는 콜백(form POST) 과 서버청구(charge_billing) 만 검증한다.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.db import models
from app.db.session import get_db
from app.services.payple import PaypleError
from main import app


_PAYPLE_EMAIL = "test-payple@test.com"


@pytest.fixture
def payple_client(db_session):
    """페이플 전용 사용자(Free 시작)로 인증된 TestClient — 다른 테스트와 격리."""
    from app.core.security import create_access_token

    user = db_session.query(models.User).filter(models.User.email == _PAYPLE_EMAIL).first()
    if not user:
        user = models.User(email=_PAYPLE_EMAIL, hashed_password="x", tier="free")
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)
    else:
        user.tier = "free"
        user.auto_renew = False
        user.billing_key = None
        user.billing_card = None
        user.billing_provider = None
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


def _get_payple_user(db):
    return db.query(models.User).filter(models.User.email == _PAYPLE_EMAIL).first()


def _success_form(oid: str) -> dict:
    """페이플 카드등록+첫청구 성공 콜백 form 데이터."""
    return {
        "PCD_PAY_RST": "success",
        "PCD_PAY_CODE": "0000",
        "PCD_PAY_MSG": "카드등록완료",
        "PCD_PAY_OID": oid,
        "PCD_PAYER_ID": "payerid_test_abc123",  # = 빌링키
        "PCD_PAY_CARDNAME": "신한카드",
        "PCD_PAY_CARDNUM": "123456******1234",
        "PCD_PAYER_NAME": "테스트",
    }


# ─── /provider ───────────────────────────────────────────

def test_provider_endpoint_returns_config(payple_client):
    resp = payple_client.get("/api/v1/payments/provider")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["provider"] in ("toss", "payple")
    assert data["payple_client_key"]
    assert "democpay" in data["payple_host"] or "cpay" in data["payple_host"]


# ─── prepare ─────────────────────────────────────────────

def test_payple_prepare_creates_order(payple_client, db_session):
    resp = payple_client.post(
        "/api/v1/payments/payple/prepare",
        json={"tier": "pro", "billing_cycle": "monthly"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["order_id"].startswith("PYP_")
    assert data["client_key"]
    assert data["host"]
    assert data["amount"] in (19_900, 9_950)  # 정가 또는 win-back 50%
    assert data["rst_url"].endswith("/payments/payple/callback")
    assert data["payer_no"]

    order = (
        db_session.query(models.PaymentOrder)
        .filter(models.PaymentOrder.order_id == data["order_id"])
        .first()
    )
    assert order is not None
    assert order.status == "PENDING"


def test_payple_prepare_rejects_invalid_tier(payple_client):
    resp = payple_client.post(
        "/api/v1/payments/payple/prepare",
        json={"tier": "free", "billing_cycle": "monthly"},
    )
    assert resp.status_code == 400


# ─── callback (빌링키 저장 + 첫 청구 + 티어 적용) ──────────

def test_payple_callback_success_upgrades(payple_client, db_session):
    prep = payple_client.post(
        "/api/v1/payments/payple/prepare",
        json={"tier": "pro", "billing_cycle": "monthly"},
    ).json()

    with patch("app.services.payple.charge_billing", return_value={"PCD_PAY_RST": "success", "PCD_PAY_OID": "CHG1"}):
        resp = payple_client.post(
            "/api/v1/payments/payple/callback",
            data=_success_form(prep["order_id"]),
            follow_redirects=False,
        )
    assert resp.status_code == 303, resp.text  # 303: POST 콜백 → GET /account (정적 POST 405 방지)
    assert "payment=success" in resp.headers["location"]
    assert "/account" in resp.headers["location"]

    db_session.expire_all()
    user = _get_payple_user(db_session)
    assert user.tier == "pro"
    assert user.auto_renew is True
    assert user.billing_key == "payerid_test_abc123"
    assert user.billing_provider == "payple"
    assert "1234" in (user.billing_card or "")
    assert user.billing_cycle == "monthly"
    assert user.subscription_expires_at is not None

    order = (
        db_session.query(models.PaymentOrder)
        .filter(models.PaymentOrder.order_id == prep["order_id"])
        .first()
    )
    assert order.status == "CONFIRMED"
    assert order.method == "card"


def test_payple_callback_ends_active_trial(payple_client, db_session):
    user = _get_payple_user(db_session)
    now = datetime.now(timezone.utc)
    user.trial_started_at = now - timedelta(days=1)
    user.trial_expires_at = now + timedelta(days=13)
    db_session.commit()

    prep = payple_client.post(
        "/api/v1/payments/payple/prepare",
        json={"tier": "pro", "billing_cycle": "monthly"},
    ).json()
    with patch("app.services.payple.charge_billing", return_value={"PCD_PAY_RST": "success"}):
        payple_client.post(
            "/api/v1/payments/payple/callback",
            data=_success_form(prep["order_id"]),
            follow_redirects=False,
        )

    sub = payple_client.get("/api/v1/payments/subscription").json()
    assert sub["is_trial"] is False
    assert sub["tier"] == "pro"
    assert sub["is_active"] is True


def test_payple_callback_failure_no_upgrade(payple_client, db_session):
    prep = payple_client.post(
        "/api/v1/payments/payple/prepare",
        json={"tier": "pro", "billing_cycle": "monthly"},
    ).json()

    form = {
        "PCD_PAY_RST": "error",
        "PCD_PAY_MSG": "카드 한도 초과",
        "PCD_PAY_OID": prep["order_id"],
    }
    resp = payple_client.post(
        "/api/v1/payments/payple/callback", data=form, follow_redirects=False
    )
    assert resp.status_code == 303
    assert "payment=fail" in resp.headers["location"]

    db_session.expire_all()
    user = _get_payple_user(db_session)
    assert user.tier != "pro"
    assert user.auto_renew is False

    order = (
        db_session.query(models.PaymentOrder)
        .filter(models.PaymentOrder.order_id == prep["order_id"])
        .first()
    )
    assert order.status == "FAILED"


def test_payple_callback_charge_failure_no_upgrade(payple_client, db_session):
    """CERT(카드등록)는 성공했으나 첫 청구(PAYM) 실패 → 구독 미적용 + 주문 FAILED.

    이 케이스가 막혀야 '청구 안 됐는데 구독만 켜지는' 매출 누락 버그가 안 생김.
    """
    prep = payple_client.post(
        "/api/v1/payments/payple/prepare",
        json={"tier": "pro", "billing_cycle": "monthly"},
    ).json()

    with patch("app.services.payple.charge_billing", side_effect=PaypleError("카드 한도 초과")):
        resp = payple_client.post(
            "/api/v1/payments/payple/callback",
            data=_success_form(prep["order_id"]),
            follow_redirects=False,
        )
    assert resp.status_code == 303
    assert "payment=fail" in resp.headers["location"]

    db_session.expire_all()
    user = _get_payple_user(db_session)
    assert user.tier != "pro"           # 구독 미적용
    assert user.auto_renew is False
    # 보안: 첫 청구 실패 시 빌링키를 저장하지 않는다 (미검증 payer_id 오염·악성 갱신청구 방지)
    assert user.billing_key is None

    order = (
        db_session.query(models.PaymentOrder)
        .filter(models.PaymentOrder.order_id == prep["order_id"])
        .first()
    )
    assert order.status == "FAILED"


def test_payple_callback_idempotent_when_confirmed(payple_client, db_session):
    """이미 CONFIRMED 된 주문에 콜백이 재전송돼도 재청구 없이 성공 응답 (중복청구 방어)."""
    prep = payple_client.post(
        "/api/v1/payments/payple/prepare",
        json={"tier": "pro", "billing_cycle": "monthly"},
    ).json()

    with patch("app.services.payple.charge_billing", return_value={"PCD_PAY_RST": "success"}) as charge:
        payple_client.post(
            "/api/v1/payments/payple/callback",
            data=_success_form(prep["order_id"]),
            follow_redirects=False,
        )
        assert charge.call_count == 1
        # 동일 콜백 재전송
        resp = payple_client.post(
            "/api/v1/payments/payple/callback",
            data=_success_form(prep["order_id"]),
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert "payment=success" in resp.headers["location"]
        assert charge.call_count == 1  # 재청구 없음


def test_payple_callback_rejects_cst_id_mismatch(payple_client, db_session):
    """콜백에 위조된 PCD_CST_ID 가 오면 청구 시도 없이 거부."""
    prep = payple_client.post(
        "/api/v1/payments/payple/prepare",
        json={"tier": "pro", "billing_cycle": "monthly"},
    ).json()

    form = _success_form(prep["order_id"])
    form["PCD_CST_ID"] = "attacker_cst_id"
    with patch("app.services.payple.charge_billing", return_value={"PCD_PAY_RST": "success"}) as charge:
        resp = payple_client.post(
            "/api/v1/payments/payple/callback", data=form, follow_redirects=False
        )
    assert resp.status_code == 303
    assert "payment=fail" in resp.headers["location"]
    assert charge.call_count == 0  # 검증 실패 → 청구 자체를 안 함

    db_session.expire_all()
    user = _get_payple_user(db_session)
    assert user.tier != "pro"
    assert user.billing_key is None


# ─── 서비스 단위: charge_billing (httpx 모킹) ─────────────

class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def test_charge_billing_success(monkeypatch):
    from app.services import payple as payple_svc

    def _fake_post(url, **kwargs):
        if url.endswith("/php/auth.php"):
            return _FakeResp({
                "result": "success",
                "AuthKey": "authkey_test",
                "cst_id": "test",
                "custKey": "abcd1234567890",
                "PCD_PAY_HOST": "https://democpay.payple.kr",
                "PCD_PAY_URL": "/php/SimplePayCardAct.php?ACT_=PAYM",
            })
        return _FakeResp({
            "PCD_PAY_RST": "success",
            "PCD_PAY_CODE": "0000",
            "PCD_PAY_OID": "PYPR_1_P_m_x",
            "PCD_PAY_TOTAL": "14900",
        })

    monkeypatch.setattr(payple_svc.httpx, "post", _fake_post)
    res = payple_svc.charge_billing(
        payer_id="payerid_x", amount=14900, oid="PYPR_1_P_m_x", goods="테스트",
    )
    assert res["PCD_PAY_RST"] == "success"
    assert res["PCD_PAY_OID"] == "PYPR_1_P_m_x"


def test_charge_billing_failure_raises(monkeypatch):
    from app.services import payple as payple_svc

    def _fake_post(url, **kwargs):
        if url.endswith("/php/auth.php"):
            return _FakeResp({"result": "success", "AuthKey": "ak",
                              "PCD_PAY_HOST": "https://democpay.payple.kr",
                              "PCD_PAY_URL": "/php/SimplePayCardAct.php?ACT_=PAYM"})
        return _FakeResp({"PCD_PAY_RST": "error", "PCD_PAY_CODE": "C001",
                          "PCD_PAY_MSG": "한도초과"})

    monkeypatch.setattr(payple_svc.httpx, "post", _fake_post)
    with pytest.raises(PaypleError):
        payple_svc.charge_billing(payer_id="x", amount=14900, oid="o", goods="g")


# ─── Celery 자동 갱신 (payple provider) ───────────────────

class _SessionWrapper:
    def __init__(self, real):
        self._real = real

    def __getattr__(self, name):
        if name == "close":
            return lambda: None
        return getattr(self._real, name)


def _fake_payple_charge(**kwargs):
    return {
        "PCD_PAY_RST": "success",
        "PCD_PAY_OID": kwargs.get("oid"),
        "PCD_PAY_CARDNAME": "신한카드",
        "PCD_PAY_CARDNUM": "123456******1234",
    }


def test_charge_due_subscriptions_payple(db_session):
    from app.tasks.billing_tasks import charge_due_subscriptions

    user = models.User(
        email="renew-payple@test.com",
        hashed_password="x",
        tier="pro",
        billing_key="payerid_existing",
        billing_provider="payple",
        billing_card="신한 ****1234",
        billing_cycle="monthly",
        auto_renew=True,
        subscription_expires_at=datetime.now(timezone.utc),
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    old_exp = user.subscription_expires_at

    with patch("app.tasks.billing_tasks.SessionLocal", lambda: _SessionWrapper(db_session)), \
         patch("app.tasks.billing_tasks.payple_charge", _fake_payple_charge):
        result = charge_due_subscriptions()

    assert result["charged"] >= 1
    db_session.expire_all()
    u = db_session.query(models.User).filter(models.User.id == user.id).first()
    new_exp = u.subscription_expires_at
    if new_exp.tzinfo is None:
        new_exp = new_exp.replace(tzinfo=timezone.utc)
    if old_exp.tzinfo is None:
        old_exp = old_exp.replace(tzinfo=timezone.utc)
    assert new_exp > old_exp
    assert u.auto_renew is True

    order = (
        db_session.query(models.PaymentOrder)
        .filter(models.PaymentOrder.user_id == user.id, models.PaymentOrder.status == "CONFIRMED")
        .first()
    )
    assert order is not None
    assert order.order_id.startswith("PYPR_")
