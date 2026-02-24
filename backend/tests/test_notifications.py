"""Tests for notification endpoints."""
import pytest

from app.db import models


class TestRegisterDevice:
    """POST /api/v1/notifications/register-device"""

    def test_requires_auth(self, client):
        """Unauthenticated request returns 401."""
        resp = client.post(
            "/api/v1/notifications/register-device",
            json={"fcm_token": "token123", "device_type": "android"},
        )
        assert resp.status_code == 401

    def test_register_device(self, free_client):
        """Register a device token."""
        resp = free_client.post(
            "/api/v1/notifications/register-device",
            json={"fcm_token": "test_fcm_token_123", "device_type": "android"},
        )
        assert resp.status_code == 204

    def test_register_device_duplicate(self, free_client):
        """Re-registering same token updates device type."""
        payload = {"fcm_token": "dup_token_123", "device_type": "android"}
        free_client.post("/api/v1/notifications/register-device", json=payload)
        payload["device_type"] = "ios"
        resp = free_client.post("/api/v1/notifications/register-device", json=payload)
        assert resp.status_code == 204

    def test_register_device_invalid_type(self, free_client):
        """Invalid device_type returns 400."""
        resp = free_client.post(
            "/api/v1/notifications/register-device",
            json={"fcm_token": "token", "device_type": "desktop"},
        )
        assert resp.status_code == 400


class TestUnregisterDevice:
    """DELETE /api/v1/notifications/unregister-device"""

    def test_unregister_device(self, free_client):
        """Unregister removes the token."""
        free_client.post(
            "/api/v1/notifications/register-device",
            json={"fcm_token": "to_remove", "device_type": "android"},
        )
        resp = free_client.request(
            "DELETE",
            "/api/v1/notifications/unregister-device",
            json={"fcm_token": "to_remove", "device_type": "android"},
        )
        assert resp.status_code == 204


class TestNotificationList:
    """GET /api/v1/notifications/list"""

    def test_empty_list(self, free_client):
        """Returns empty list for user with no notifications."""
        resp = free_client.get("/api/v1/notifications/list")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_list_with_notifications(self, free_client, db_session):
        """Returns notifications after inserting some."""
        user = db_session.query(models.User).filter(
            models.User.email == "test-free@test.com"
        ).first()
        if user:
            noti = models.Notification(
                user_id=user.id,
                title="새 공고 알림",
                body="관심 공고가 등록되었습니다.",
                noti_type="new_bid",
            )
            db_session.add(noti)
            db_session.commit()

        resp = free_client.get("/api/v1/notifications/list")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
        assert data[0]["noti_type"] == "new_bid"


class TestMarkRead:
    """POST /api/v1/notifications/{id}/read"""

    def test_mark_nonexistent_returns_404(self, free_client):
        """Marking nonexistent notification returns 404."""
        resp = free_client.post("/api/v1/notifications/99999/read")
        assert resp.status_code == 404

    def test_mark_as_read(self, free_client, db_session):
        """Mark notification as read."""
        user = db_session.query(models.User).filter(
            models.User.email == "test-free@test.com"
        ).first()
        if user:
            noti = models.Notification(
                user_id=user.id,
                title="읽기 테스트",
                body="test",
                noti_type="new_bid",
            )
            db_session.add(noti)
            db_session.commit()
            db_session.refresh(noti)

            resp = free_client.post(f"/api/v1/notifications/{noti.id}/read")
            assert resp.status_code == 204


class TestMarkAllRead:
    """POST /api/v1/notifications/read-all"""

    def test_mark_all_read(self, free_client):
        """Mark all as read succeeds."""
        resp = free_client.post("/api/v1/notifications/read-all")
        assert resp.status_code == 204


class TestUnreadCount:
    """GET /api/v1/notifications/unread-count"""

    def test_unread_count(self, free_client):
        """Returns unread count."""
        resp = free_client.get("/api/v1/notifications/unread-count")
        assert resp.status_code == 200
        data = resp.json()
        assert "count" in data
        assert isinstance(data["count"], int)
