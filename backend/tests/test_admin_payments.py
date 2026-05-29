"""
관리자 결제 관리 엔드포인트 테스트.

환불 흐름은 Toss API 호출이 필요해 mock 으로 검증.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from app.db import models


def _make_payment(db, user_id, order_id, amount, status="CONFIRMED", **kwargs):
    p = models.PaymentOrder(
        user_id=user_id, order_id=order_id, amount=amount, status=status,
        payment_key=kwargs.get("payment_key", "tossPaymentKey_" + order_id),
        confirmed_at=kwargs.get("confirmed_at", datetime.now(timezone.utc)),
        method=kwargs.get("method", "카드"),
    )
    db.add(p)
    db.commit()
    return p


# ── /admin/payments 목록 ──────────────────────────────────

def test_list_payments_basic(admin_client, db_session):
    user = db_session.query(models.User).filter_by(email="test-admin@test.com").first()
    _make_payment(db_session, user.id, "SUB_LIST_1", 14900)
    _make_payment(db_session, user.id, "SUB_LIST_2", 140000)
    _make_payment(db_session, user.id, "BIDEASY_LIST_3", 5000)

    resp = admin_client.get("/api/v1/admin/payments?page=1&size=10")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 3


def test_list_payments_filter_status(admin_client, db_session):
    user = db_session.query(models.User).filter_by(email="test-admin@test.com").first()
    _make_payment(db_session, user.id, "PENDING_X1", 5000, status="PENDING")

    resp = admin_client.get("/api/v1/admin/payments?status=PENDING")
    data = resp.json()
    assert all(p["status"] == "PENDING" for p in data["items"])


def test_list_payments_search(admin_client, db_session):
    user = db_session.query(models.User).filter_by(email="test-admin@test.com").first()
    _make_payment(db_session, user.id, "SEARCHABLE_UNIQUE_X", 5000)

    resp = admin_client.get("/api/v1/admin/payments?search=SEARCHABLE_UNIQUE")
    data = resp.json()
    assert any(p["order_id"] == "SEARCHABLE_UNIQUE_X" for p in data["items"])


# ── /admin/payments/{id} 상세 ─────────────────────────────

def test_get_payment_detail(admin_client, db_session):
    user = db_session.query(models.User).filter_by(email="test-admin@test.com").first()
    _make_payment(db_session, user.id, "SUB_DETAIL_1", 14900)

    resp = admin_client.get("/api/v1/admin/payments/SUB_DETAIL_1")
    assert resp.status_code == 200
    data = resp.json()
    assert data["order_id"] == "SUB_DETAIL_1"
    assert data["user"] is not None
    assert data["order_kind"] == "subscription"


def test_get_payment_detail_404(admin_client):
    resp = admin_client.get("/api/v1/admin/payments/NONEXISTENT")
    assert resp.status_code == 404


# ── 환불 처리 ──────────────────────────────────────────────

class _MockTossResponse:
    """httpx.Response mock."""
    def __init__(self, status_code, json_data):
        self.status_code = status_code
        self._json_data = json_data
        self.text = str(json_data)

    def json(self):
        return self._json_data


@pytest.fixture
def mock_toss_ok():
    """Toss 환불 API 성공 응답 mock."""
    mock_resp = _MockTossResponse(
        200,
        {
            "status": "CANCELED",
            "cancels": [{"transactionKey": "TXN_REFUND_KEY_1", "cancelAmount": 0}],
        },
    )
    with patch("app.services.payments_refund.httpx.AsyncClient") as mock_client:
        instance = AsyncMock()
        instance.post = AsyncMock(return_value=mock_resp)
        mock_client.return_value.__aenter__.return_value = instance
        mock_client.return_value.__aexit__.return_value = None
        yield mock_resp


def test_refund_full(admin_client, db_session, mock_toss_ok):
    user = db_session.query(models.User).filter_by(email="test-admin@test.com").first()
    p = _make_payment(db_session, user.id, "SUB_REFUND_FULL", 140000)

    resp = admin_client.post(
        f"/api/v1/admin/payments/{p.order_id}/refund",
        json={"reason": "고객 요청"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_full_refund"] is True
    assert data["refund_amount"] == 140000

    db_session.refresh(p)
    assert p.refund_amount == 140000
    assert p.refunded_at is not None


def test_refund_partial(admin_client, db_session, mock_toss_ok):
    user = db_session.query(models.User).filter_by(email="test-admin@test.com").first()
    p = _make_payment(db_session, user.id, "SUB_REFUND_PARTIAL", 140000)

    resp = admin_client.post(
        f"/api/v1/admin/payments/{p.order_id}/refund",
        json={"amount": 50000, "reason": "부분"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["refund_amount"] == 50000
    assert data["is_full_refund"] is False

    db_session.refresh(p)
    assert p.refund_amount == 50000
    assert p.refunded_at is None  # 부분 환불은 refunded_at 안 찍음


def test_refund_idempotent(admin_client, db_session, mock_toss_ok):
    """이미 전액 환불된 주문 → 409."""
    user = db_session.query(models.User).filter_by(email="test-admin@test.com").first()
    p = _make_payment(db_session, user.id, "SUB_REFUND_IDEM", 14900)

    r1 = admin_client.post(f"/api/v1/admin/payments/{p.order_id}/refund", json={"reason": "1"})
    assert r1.status_code == 200

    r2 = admin_client.post(f"/api/v1/admin/payments/{p.order_id}/refund", json={"reason": "2"})
    assert r2.status_code == 409


def test_refund_revoke_tier(admin_client, db_session, mock_toss_ok):
    user = db_session.query(models.User).filter_by(email="test-admin@test.com").first()
    # 사용자 Pro 상태 만들기
    user.tier = "pro"
    user.subscription_expires_at = datetime.now(timezone.utc) + timedelta(days=30)
    db_session.commit()
    p = _make_payment(db_session, user.id, "SUB_REVOKE_X", 14900)

    resp = admin_client.post(
        f"/api/v1/admin/payments/{p.order_id}/refund",
        json={"reason": "회수", "revoke_tier": True},
    )
    assert resp.status_code == 200
    db_session.refresh(user)
    assert user.tier == "free"


def test_refund_not_confirmed(admin_client, db_session):
    user = db_session.query(models.User).filter_by(email="test-admin@test.com").first()
    p = _make_payment(db_session, user.id, "PENDING_REFUND_X", 5000, status="PENDING")

    resp = admin_client.post(
        f"/api/v1/admin/payments/{p.order_id}/refund",
        json={"reason": "X"},
    )
    assert resp.status_code == 400


# ── 단건 PENDING 취소 ──────────────────────────────────────

def test_cancel_pending_single(admin_client, db_session):
    user = db_session.query(models.User).filter_by(email="test-admin@test.com").first()
    p = _make_payment(db_session, user.id, "SUB_CANCEL_SINGLE_1", 14900, status="PENDING")

    resp = admin_client.post(f"/api/v1/admin/payments/{p.order_id}/cancel-pending")
    assert resp.status_code == 200
    assert resp.json()["status"] == "FAILED"

    db_session.refresh(p)
    assert p.status == "FAILED"
    assert "취소" in p.fail_reason


def test_cancel_pending_404(admin_client):
    resp = admin_client.post("/api/v1/admin/payments/NONEXISTENT_X/cancel-pending")
    assert resp.status_code == 404


def test_cancel_pending_wrong_status(admin_client, db_session):
    """이미 CONFIRMED 면 400."""
    user = db_session.query(models.User).filter_by(email="test-admin@test.com").first()
    p = _make_payment(db_session, user.id, "SUB_CANCEL_BAD_1", 14900, status="CONFIRMED")

    resp = admin_client.post(f"/api/v1/admin/payments/{p.order_id}/cancel-pending")
    assert resp.status_code == 400


# ── PENDING 정리 ───────────────────────────────────────────

def test_cleanup_pending(admin_client, db_session):
    user = db_session.query(models.User).filter_by(email="test-admin@test.com").first()
    # 25시간 전 PENDING 2건 + 1시간 전 PENDING 1건
    old = datetime.now(timezone.utc) - timedelta(hours=25)
    fresh = datetime.now(timezone.utc) - timedelta(hours=1)
    p1 = models.PaymentOrder(user_id=user.id, order_id="CLEAN_OLD_1", amount=5000, status="PENDING", created_at=old)
    p2 = models.PaymentOrder(user_id=user.id, order_id="CLEAN_OLD_2", amount=5000, status="PENDING", created_at=old)
    p3 = models.PaymentOrder(user_id=user.id, order_id="CLEAN_FRESH_1", amount=5000, status="PENDING", created_at=fresh)
    db_session.add_all([p1, p2, p3])
    db_session.commit()

    resp = admin_client.post("/api/v1/admin/payments/cleanup-pending", json={"hours": 24})
    assert resp.status_code == 200
    assert resp.json()["cleaned"] >= 2

    db_session.refresh(p1)
    db_session.refresh(p3)
    assert p1.status == "FAILED"
    assert p3.status == "PENDING"  # 24시간 미만은 그대로
