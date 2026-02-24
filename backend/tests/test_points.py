"""Tests for points system endpoints."""
import pytest


class TestPointBalance:
    """GET /api/v1/points/balance"""

    def test_requires_auth(self, client):
        """Unauthenticated request returns 401."""
        resp = client.get("/api/v1/points/balance")
        assert resp.status_code == 401

    def test_get_balance(self, free_client):
        """Returns point balance for authenticated user."""
        resp = free_client.get("/api/v1/points/balance")
        assert resp.status_code == 200
        data = resp.json()
        assert "points" in data
        assert "formatted" in data
        assert isinstance(data["points"], int)


class TestDailyFree:
    """GET /api/v1/points/daily-free"""

    def test_daily_free_status(self, free_client):
        """Returns daily free copy status."""
        resp = free_client.get("/api/v1/points/daily-free")
        assert resp.status_code == 200
        data = resp.json()
        assert data["available"] is True
        assert data["used_today"] == 0
        assert data["max_daily"] == 1


class TestPointDeduct:
    """POST /api/v1/points/deduct"""

    def test_deduct_free_copy(self, free_client, sample_notice):
        """First deduction of the day is free."""
        resp = free_client.post(
            "/api/v1/points/deduct",
            json={"bid_no": "TEST-001"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["was_free"] is True
        assert data["cost"] == 0

    def test_deduct_paid_copy(self, free_client, sample_notice):
        """Second deduction costs points."""
        # Use up free copy
        free_client.post("/api/v1/points/deduct", json={"bid_no": "TEST-001"})
        # Second copy should cost 500
        resp = free_client.post(
            "/api/v1/points/deduct",
            json={"bid_no": "TEST-001"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["cost"] == 500
        assert data["was_free"] is False

    def test_deduct_insufficient_points(self, free_client, sample_notice, db_session):
        """Deduction with no points returns 402."""
        from app.db import models

        # Use free copy
        free_client.post("/api/v1/points/deduct", json={"bid_no": "TEST-001"})

        # Set points to 0
        user = db_session.query(models.User).filter(
            models.User.email == "test-free@test.com"
        ).first()
        if user:
            user.points = 0
            db_session.commit()

        resp = free_client.post(
            "/api/v1/points/deduct",
            json={"bid_no": "TEST-001"},
        )
        assert resp.status_code == 402


class TestPointCharge:
    """POST /api/v1/points/charge"""

    def test_charge_positive_amount(self, free_client):
        """Charging positive amount increases balance."""
        resp = free_client.post(
            "/api/v1/points/charge",
            json={"amount": 1000},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["charged_amount"] == 1000

    def test_charge_zero_amount(self, free_client):
        """Zero amount returns 400."""
        resp = free_client.post(
            "/api/v1/points/charge",
            json={"amount": 0},
        )
        assert resp.status_code == 400

    def test_charge_negative_amount(self, free_client):
        """Negative amount returns 400."""
        resp = free_client.post(
            "/api/v1/points/charge",
            json={"amount": -1000},
        )
        assert resp.status_code == 400


class TestPointHistory:
    """GET /api/v1/points/history"""

    def test_get_history(self, free_client):
        """Returns transaction history."""
        resp = free_client.get("/api/v1/points/history")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_history_limit(self, free_client):
        """Limit parameter works."""
        resp = free_client.get("/api/v1/points/history?limit=5")
        assert resp.status_code == 200
        assert len(resp.json()) <= 5
