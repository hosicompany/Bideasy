"""
관리자 사용자 관리 엔드포인트 테스트.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.db import models


@pytest.fixture
def sample_users(db_session):
    """검색·필터 테스트용 사용자 5명 (멱등 — 이미 있으면 재사용)."""
    now = datetime.now(timezone.utc)
    specs = [
        ("alice@test.com", "알파", "free", None, None),
        ("bob@test.com", "베타", "pro", None, None),
        ("charlie@test.com", "감마", "free", now, now + timedelta(days=10)),
        ("dave@test.com", "델타", "pro_plus", None, None),
        ("eve@test.com", "입실론", "free", now - timedelta(days=30), now - timedelta(days=16)),
    ]
    users = []
    for email, company, tier, ts, te in specs:
        u = db_session.query(models.User).filter_by(email=email).first()
        if u is None:
            u = models.User(
                email=email, company_name=company, hashed_password="x", tier=tier,
                trial_started_at=ts, trial_expires_at=te,
            )
            db_session.add(u)
        users.append(u)
    db_session.commit()
    for u in users:
        db_session.refresh(u)
    return users


# ── /admin/users 목록 ──────────────────────────────────────

def test_list_users_basic(admin_client, sample_users):
    resp = admin_client.get("/api/v1/admin/users?page=1&size=10")
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert data["total"] >= 5
    assert all("id" in u and "email" in u for u in data["items"])


def test_list_users_search(admin_client, sample_users):
    resp = admin_client.get("/api/v1/admin/users?search=alice")
    data = resp.json()
    emails = [u["email"] for u in data["items"]]
    assert "alice@test.com" in emails


def test_list_users_filter_tier(admin_client, sample_users):
    resp = admin_client.get("/api/v1/admin/users?tier=pro_plus")
    data = resp.json()
    assert all(u["tier"] == "pro_plus" for u in data["items"])


def test_list_users_filter_trial_active(admin_client, sample_users):
    resp = admin_client.get("/api/v1/admin/users?trial=active")
    data = resp.json()
    assert all(u["is_trial_active"] for u in data["items"])


def test_list_users_pagination(admin_client, sample_users):
    resp = admin_client.get("/api/v1/admin/users?page=1&size=2")
    data = resp.json()
    assert len(data["items"]) <= 2
    assert data["size"] == 2
    assert data["page"] == 1


# ── /admin/users/{id} 상세 ─────────────────────────────────

def test_get_user_detail(admin_client, sample_users):
    user_id = sample_users[0].id
    resp = admin_client.get(f"/api/v1/admin/users/{user_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == user_id
    assert "recent_payments" in data
    assert "recent_points" in data
    assert "total_paid" in data


def test_get_user_detail_404(admin_client):
    resp = admin_client.get("/api/v1/admin/users/999999")
    assert resp.status_code == 404


# ── PATCH tier ─────────────────────────────────────────────

def test_update_user_tier(admin_client, sample_users):
    user_id = sample_users[0].id  # free → pro
    future = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    resp = admin_client.patch(
        f"/api/v1/admin/users/{user_id}/tier",
        json={"tier": "pro", "expires_at": future, "reason": "VIP"},
    )
    assert resp.status_code == 200
    assert resp.json()["tier"] == "pro"


def test_update_user_tier_invalid(admin_client, sample_users):
    user_id = sample_users[0].id
    resp = admin_client.patch(
        f"/api/v1/admin/users/{user_id}/tier",
        json={"tier": "premium", "reason": "X"},
    )
    assert resp.status_code == 400


# ── Trial 연장·만료 ────────────────────────────────────────

def test_extend_trial(admin_client, sample_users, db_session):
    user_id = sample_users[2].id  # trial active 사용자
    before = sample_users[2].trial_expires_at
    resp = admin_client.post(
        f"/api/v1/admin/users/{user_id}/extend-trial",
        json={"days": 7},
    )
    assert resp.status_code == 200
    db_session.refresh(sample_users[2])
    new_exp = sample_users[2].trial_expires_at
    if before.tzinfo is None:
        before = before.replace(tzinfo=timezone.utc)
    if new_exp.tzinfo is None:
        new_exp = new_exp.replace(tzinfo=timezone.utc)
    assert (new_exp - before).days >= 6  # ±1 일 허용


def test_expire_trial(admin_client, sample_users, db_session):
    user_id = sample_users[2].id
    resp = admin_client.post(f"/api/v1/admin/users/{user_id}/expire-trial")
    assert resp.status_code == 200
    db_session.refresh(sample_users[2])
    exp = sample_users[2].trial_expires_at
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    assert exp <= datetime.now(timezone.utc) + timedelta(seconds=10)


# ── DELETE 사용자 cascade ──────────────────────────────────

def _make_fresh_user(db, email: str, tier: str = "free", sub_expires=None) -> models.User:
    """테스트 격리용 신규 사용자 (이미 있으면 재사용)."""
    u = db.query(models.User).filter_by(email=email).first()
    if u is None:
        u = models.User(email=email, hashed_password="x", tier=tier,
                        subscription_expires_at=sub_expires)
        db.add(u)
        db.commit()
        db.refresh(u)
    return u


def test_delete_user_cascade(admin_client, db_session):
    user = _make_fresh_user(db_session, "del-cascade@test.com", tier="free")
    user_id = user.id
    # 종속 데이터 생성: PointTransaction + Notification + DeviceToken
    db_session.add(models.PointTransaction(
        user_id=user_id, amount=1000, balance_after=1000,
        tx_type="CHARGE", description="테스트",
    ))
    db_session.add(models.Notification(
        user_id=user_id, title="X", body="Y", noti_type="info",
    ))
    db_session.add(models.DeviceToken(
        user_id=user_id, fcm_token="X_DEL", device_type="web",
    ))
    db_session.commit()

    resp = admin_client.delete(f"/api/v1/admin/users/{user_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["deleted"]["point_transactions"] >= 1
    assert data["deleted"]["notifications"] >= 1
    assert data["deleted"]["device_tokens"] >= 1

    assert db_session.query(models.User).filter_by(id=user_id).first() is None
    assert db_session.query(models.PointTransaction).filter_by(user_id=user_id).count() == 0


def test_delete_user_preserves_payment(admin_client, db_session):
    """PaymentOrder 는 user_id=NULL 로 보존 (회계 기록)."""
    user = _make_fresh_user(db_session, "del-preserve@test.com", tier="free")
    user_id = user.id
    p = models.PaymentOrder(
        user_id=user_id, order_id="SUB_PRESERVE_TEST",
        amount=140000, status="CONFIRMED",
        confirmed_at=datetime.now(timezone.utc),
    )
    db_session.add(p)
    db_session.commit()

    resp = admin_client.delete(f"/api/v1/admin/users/{user_id}")
    assert resp.status_code == 200
    db_session.commit()

    p_after = db_session.query(models.PaymentOrder).filter_by(order_id="SUB_PRESERVE_TEST").first()
    assert p_after is not None
    assert p_after.user_id is None


def test_delete_user_refuses_active_subscription(admin_client, db_session):
    """활성 유료 구독 → 409 (force=false)."""
    user = _make_fresh_user(
        db_session, "del-active@test.com", tier="pro_plus",
        sub_expires=datetime.now(timezone.utc) + timedelta(days=30),
    )
    resp = admin_client.delete(f"/api/v1/admin/users/{user.id}")
    assert resp.status_code == 409
    assert "환불" in resp.json()["detail"]


def test_delete_self_forbidden(admin_client, db_session):
    """본인 계정 삭제 금지."""
    me = db_session.query(models.User).filter_by(email="test-admin@test.com").first()
    resp = admin_client.delete(f"/api/v1/admin/users/{me.id}")
    assert resp.status_code == 400
    assert "본인" in resp.json()["detail"]


# ── 포인트 지급 ────────────────────────────────────────────

def test_grant_points(admin_client, sample_users, db_session):
    user = sample_users[2]
    before = user.points or 0
    resp = admin_client.post(
        f"/api/v1/admin/users/{user.id}/grant-points",
        json={"amount": 5000, "reason": "테스트"},
    )
    assert resp.status_code == 200
    assert resp.json()["new_balance"] == before + 5000

    tx = db_session.query(models.PointTransaction).filter(
        models.PointTransaction.user_id == user.id,
        models.PointTransaction.tx_type == "ADMIN_GRANT",
    ).first()
    assert tx is not None
    assert tx.amount == 5000
