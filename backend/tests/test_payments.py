"""Tests for payment and subscription endpoints."""
import pytest


class TestCreateOrder:
    """POST /api/v1/payments/create-order"""

    def test_requires_auth(self, client):
        """Unauthenticated request returns 401."""
        resp = client.post("/api/v1/payments/create-order", json={"amount": 5000})
        assert resp.status_code == 401

    def test_create_order_valid_amount(self, free_client):
        """Valid amount creates an order."""
        resp = free_client.post("/api/v1/payments/create-order", json={"amount": 5000})
        assert resp.status_code == 200
        data = resp.json()
        assert data["amount"] == 5000
        assert "order_id" in data
        assert data["order_id"].startswith("BIDEASY_")
        assert "toss_client_key" in data

    def test_create_order_invalid_amount(self, free_client):
        """Non-allowed amount returns 400."""
        resp = free_client.post("/api/v1/payments/create-order", json={"amount": 999})
        assert resp.status_code == 400

    def test_create_order_all_valid_amounts(self, free_client):
        """All ALLOWED_AMOUNTS should work."""
        for amount in [5000, 10000, 30000, 50000]:
            resp = free_client.post("/api/v1/payments/create-order", json={"amount": amount})
            assert resp.status_code == 200


class TestPaymentCallbacks:
    """GET /api/v1/payments/success and /fail"""

    def test_success_unknown_order_redirects(self, client):
        """Unknown orderId redirects with fail message."""
        resp = client.get(
            "/api/v1/payments/success",
            params={"paymentKey": "pk_test", "orderId": "UNKNOWN", "amount": 5000},
            follow_redirects=False,
        )
        assert resp.status_code == 307
        assert "fail" in resp.headers["location"]

    def test_fail_callback_redirects(self, client):
        """Fail callback redirects to frontend."""
        resp = client.get(
            "/api/v1/payments/fail",
            params={"code": "PAY_CANCEL", "message": "취소됨", "orderId": "UNKNOWN"},
            follow_redirects=False,
        )
        assert resp.status_code == 307

    def test_success_amount_mismatch(self, free_client, db_session):
        """Amount mismatch between order and callback fails the order."""
        # Create order first
        order_resp = free_client.post("/api/v1/payments/create-order", json={"amount": 5000})
        order_id = order_resp.json()["order_id"]

        # Callback with wrong amount
        resp = free_client.get(
            "/api/v1/payments/success",
            params={"paymentKey": "pk_test", "orderId": order_id, "amount": 9999},
            follow_redirects=False,
        )
        assert resp.status_code == 307
        assert "fail" in resp.headers["location"]


class TestSubscription:
    """POST /api/v1/payments/subscribe"""

    def test_subscribe_requires_auth(self, client):
        """Unauthenticated request returns 401."""
        resp = client.post(
            "/api/v1/payments/subscribe",
            json={"tier": "pro", "billing_cycle": "monthly"},
        )
        assert resp.status_code == 401

    def test_subscribe_valid(self, free_client):
        """Valid subscription order creation."""
        resp = free_client.post(
            "/api/v1/payments/subscribe",
            json={"tier": "pro", "billing_cycle": "monthly"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["tier"] == "pro"
        assert data["order_id"].startswith("SUB_")
        assert data["amount"] > 0

    def test_subscribe_invalid_tier(self, free_client):
        """Invalid tier returns 400."""
        resp = free_client.post(
            "/api/v1/payments/subscribe",
            json={"tier": "invalid_tier", "billing_cycle": "monthly"},
        )
        assert resp.status_code == 400

    def test_subscribe_invalid_cycle(self, free_client):
        """Invalid billing cycle returns 400."""
        resp = free_client.post(
            "/api/v1/payments/subscribe",
            json={"tier": "pro", "billing_cycle": "weekly"},
        )
        assert resp.status_code == 400

    def test_subscribe_annual(self, free_client):
        """Annual subscription has different pricing."""
        monthly = free_client.post(
            "/api/v1/payments/subscribe",
            json={"tier": "pro", "billing_cycle": "monthly"},
        ).json()
        annual = free_client.post(
            "/api/v1/payments/subscribe",
            json={"tier": "pro", "billing_cycle": "annual"},
        ).json()
        # Annual should be more expensive (10 months worth)
        assert annual["amount"] > monthly["amount"]


class TestSubscriptionStatus:
    """GET /api/v1/payments/subscription"""

    def test_get_subscription_free_user(self, free_client):
        """Free user has free tier."""
        resp = free_client.get("/api/v1/payments/subscription")
        assert resp.status_code == 200
        data = resp.json()
        assert data["tier"] == "free"
        assert data["is_active"] is False

    def test_get_subscription_pro_user(self, pro_client):
        """Pro user has active subscription."""
        resp = pro_client.get("/api/v1/payments/subscription")
        assert resp.status_code == 200
        data = resp.json()
        assert data["tier"] == "pro"


class TestCancelSubscription:
    """POST /api/v1/payments/subscribe/cancel"""

    def test_cancel_free_user_returns_400(self, free_client):
        """Free user cannot cancel (no subscription)."""
        resp = free_client.post("/api/v1/payments/subscribe/cancel")
        assert resp.status_code == 400

    def test_cancel_pro_user(self, pro_client):
        """Pro user can cancel subscription."""
        resp = pro_client.post("/api/v1/payments/subscribe/cancel")
        assert resp.status_code == 200
        assert resp.json()["success"] is True
