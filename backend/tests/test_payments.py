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
        # Annual should be more expensive (1년치 통합 결제)
        assert annual["amount"] > monthly["amount"]

    def test_subscribe_exact_prices(self, free_client):
        """결제 금액이 정확한지 — 이전 버그(ANNUAL_MONTHLY_PRICES × 10 = 124,000) 재발 방지."""
        from app.schemas.subscription import MONTHLY_PRICES, ANNUAL_PRICES, TIER_PRO, TIER_PRO_PLUS

        # Pro 월간
        resp = free_client.post(
            "/api/v1/payments/subscribe",
            json={"tier": "pro", "billing_cycle": "monthly"},
        )
        assert resp.json()["amount"] == MONTHLY_PRICES[TIER_PRO]  # 14,900

        # Pro 연간 — 20% 할인 + 라운딩 = 140,000
        resp = free_client.post(
            "/api/v1/payments/subscribe",
            json={"tier": "pro", "billing_cycle": "annual"},
        )
        assert resp.json()["amount"] == ANNUAL_PRICES[TIER_PRO]  # 140,000
        assert resp.json()["amount"] == 140_000

        # Pro+ 월간
        resp = free_client.post(
            "/api/v1/payments/subscribe",
            json={"tier": "pro_plus", "billing_cycle": "monthly"},
        )
        assert resp.json()["amount"] == MONTHLY_PRICES[TIER_PRO_PLUS]  # 29,900

        # Pro+ 연간 = 280,000
        resp = free_client.post(
            "/api/v1/payments/subscribe",
            json={"tier": "pro_plus", "billing_cycle": "annual"},
        )
        assert resp.json()["amount"] == ANNUAL_PRICES[TIER_PRO_PLUS]  # 280,000
        assert resp.json()["amount"] == 280_000

    def test_annual_discount_is_20_percent(self, free_client):
        """연간 가격이 월간 × 12 대비 20% 할인 (실제 ~21.7%) 인지."""
        monthly = free_client.post(
            "/api/v1/payments/subscribe",
            json={"tier": "pro", "billing_cycle": "monthly"},
        ).json()["amount"]
        annual = free_client.post(
            "/api/v1/payments/subscribe",
            json={"tier": "pro", "billing_cycle": "annual"},
        ).json()["amount"]
        regular_total = monthly * 12
        discount_pct = (regular_total - annual) / regular_total * 100
        # 표기 20% 약속 → 실제 라운딩으로 20~22% 범위 보장
        assert 20.0 <= discount_pct <= 22.5, f"할인율 {discount_pct:.2f}% (기대 20~22%)"


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


class TestPaymentHistory:
    """GET /api/v1/payments/history — 마이페이지 결제 내역"""

    def test_history_requires_auth(self, client):
        resp = client.get("/api/v1/payments/history")
        assert resp.status_code == 401

    def test_history_empty_for_new_user(self, free_client):
        """결제 이력 없는 신규 사용자는 빈 목록."""
        resp = free_client.get("/api/v1/payments/history")
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0

    def test_history_returns_confirmed_orders(self, free_client, db_session):
        """본인의 CONFIRMED 주문만 반환 (PENDING/FAILED 제외)."""
        from datetime import datetime, timezone
        from app.db import models

        user = (
            db_session.query(models.User)
            .filter(models.User.email == "test-free@test.com")
            .first()
        )
        # CONFIRMED 주문 2개 + PENDING 1개 + FAILED 1개
        db_session.add_all([
            models.PaymentOrder(
                user_id=user.id, order_id="SUB_T1", amount=140000,
                status="CONFIRMED", method="카드",
                confirmed_at=datetime.now(timezone.utc),
            ),
            models.PaymentOrder(
                user_id=user.id, order_id="BIDEASY_T2", amount=5000,
                status="CONFIRMED", method="카드",
                confirmed_at=datetime.now(timezone.utc),
            ),
            models.PaymentOrder(
                user_id=user.id, order_id="SUB_T3_pending", amount=29900,
                status="PENDING",
            ),
            models.PaymentOrder(
                user_id=user.id, order_id="SUB_T4_failed", amount=29900,
                status="FAILED", fail_reason="card declined",
            ),
        ])
        db_session.commit()

        resp = free_client.get("/api/v1/payments/history")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        order_ids = {item["order_id"] for item in data["items"]}
        assert order_ids == {"SUB_T1", "BIDEASY_T2"}

        # order_kind 분류 확인 — SUB_ prefix → subscription, 그 외 → points
        kinds = {item["order_id"]: item["order_kind"] for item in data["items"]}
        assert kinds["SUB_T1"] == "subscription"
        assert kinds["BIDEASY_T2"] == "points"

    def test_history_only_own_orders(self, free_client, db_session):
        """다른 사용자의 결제는 보이지 않음."""
        from datetime import datetime, timezone
        from app.db import models

        # 다른 사용자 생성
        other_user = models.User(email="other@test.com", hashed_password="x")
        db_session.add(other_user)
        db_session.commit()
        db_session.refresh(other_user)

        # 다른 사용자의 주문 1건
        db_session.add(
            models.PaymentOrder(
                user_id=other_user.id, order_id="SUB_OTHER", amount=140000,
                status="CONFIRMED", confirmed_at=datetime.now(timezone.utc),
            )
        )
        db_session.commit()

        resp = free_client.get("/api/v1/payments/history")
        assert resp.status_code == 200
        data = resp.json()
        order_ids = {item["order_id"] for item in data["items"]}
        assert "SUB_OTHER" not in order_ids
