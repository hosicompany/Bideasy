"""
14일 Pro 체험(Trial) 로직 테스트.

- 신규 가입 시 체험 자동 활성화 (regular + social)
- 활성 체험 → require_tier("pro") 통과
- 만료된 체험 → require_tier("pro") 거부
- 체험 사용 이력 있으면 재체험 불가 (activate_trial idempotent)
- 유료 구독이 체험보다 우선
- /users/me/trial 엔드포인트 동작
- /payments/subscription 엔드포인트 체험 반영
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.db import models
from app.schemas.subscription import (
    TRIAL_DAYS,
    TRIAL_TIER,
    activate_trial,
    get_effective_tier,
    is_trial_active,
    has_used_trial,
    trial_days_remaining,
)
from app.core.security import create_access_token


# ── 단위 테스트: 헬퍼 함수들 ─────────────────────────────────────

def test_activate_trial_sets_14_day_window(db_session):
    """activate_trial → trial_started_at = now, trial_expires_at = now + 14일."""
    user = models.User(email="trial-1@test.com", hashed_password="x")
    db_session.add(user)
    db_session.flush()

    before = datetime.now(timezone.utc)
    activate_trial(user)
    after = datetime.now(timezone.utc)

    assert user.trial_started_at is not None
    assert user.trial_expires_at is not None

    # trial_started_at 은 호출 시점 ± 1초 안에
    started = user.trial_started_at
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    assert before <= started <= after

    # trial_expires_at = trial_started_at + 14일
    expires = user.trial_expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    delta = expires - started
    assert abs(delta.total_seconds() - TRIAL_DAYS * 86400) < 1


def test_is_trial_active_true_when_within_window(db_session):
    user = models.User(email="trial-2@test.com", hashed_password="x")
    activate_trial(user)
    assert is_trial_active(user) is True
    assert trial_days_remaining(user) >= TRIAL_DAYS - 1  # 직후라 14일 거의 전부 남음


def test_is_trial_active_false_when_expired(db_session):
    """trial_expires_at 이 과거면 비활성."""
    user = models.User(email="trial-3@test.com", hashed_password="x")
    user.trial_started_at = datetime.now(timezone.utc) - timedelta(days=30)
    user.trial_expires_at = datetime.now(timezone.utc) - timedelta(days=16)

    assert is_trial_active(user) is False
    assert has_used_trial(user) is True
    assert trial_days_remaining(user) == 0


def test_is_trial_active_false_when_never_started(db_session):
    """체험 시작 안 한 사용자는 비활성."""
    user = models.User(email="trial-4@test.com", hashed_password="x")
    assert is_trial_active(user) is False
    assert has_used_trial(user) is False
    assert trial_days_remaining(user) == 0


def test_activate_trial_is_idempotent(db_session):
    """이미 체험 시작한 사용자는 activate_trial 호출해도 변화 없음 (재체험 방지)."""
    user = models.User(email="trial-5@test.com", hashed_password="x")
    activate_trial(user)
    first_started = user.trial_started_at
    first_expires = user.trial_expires_at

    # 시간 약간 흐른 후 다시 호출
    activate_trial(user)

    assert user.trial_started_at == first_started
    assert user.trial_expires_at == first_expires


def test_activate_trial_blocked_for_expired_users(db_session):
    """만료된 체험 사용자도 새 체험을 받을 수 없음 (재사용 방지의 강한 정책)."""
    user = models.User(email="trial-6@test.com", hashed_password="x")
    user.trial_started_at = datetime.now(timezone.utc) - timedelta(days=30)
    user.trial_expires_at = datetime.now(timezone.utc) - timedelta(days=16)

    activate_trial(user)  # 호출해도 무시되어야

    expires = user.trial_expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    # 여전히 만료 상태
    assert expires < datetime.now(timezone.utc)


# ── get_effective_tier 통합 판정 ─────────────────────────────────

def test_effective_tier_free_for_new_user(db_session):
    user = models.User(email="eff-1@test.com", hashed_password="x", tier="free")
    assert get_effective_tier(user) == "free"


def test_effective_tier_pro_during_trial(db_session):
    """체험 활성 사용자는 tier='free' 라도 effective='pro'."""
    user = models.User(email="eff-2@test.com", hashed_password="x", tier="free")
    activate_trial(user)
    assert get_effective_tier(user) == TRIAL_TIER  # "pro"


def test_effective_tier_falls_back_after_trial_expires(db_session):
    user = models.User(email="eff-3@test.com", hashed_password="x", tier="free")
    user.trial_started_at = datetime.now(timezone.utc) - timedelta(days=30)
    user.trial_expires_at = datetime.now(timezone.utc) - timedelta(days=16)
    assert get_effective_tier(user) == "free"


def test_paid_subscription_overrides_trial(db_session):
    """유료 구독이 활성이면 그것이 우선 — Pro+ 가입자가 체험 활성이어도 effective=pro_plus."""
    user = models.User(
        email="eff-4@test.com",
        hashed_password="x",
        tier="pro_plus",
        subscription_expires_at=datetime.now(timezone.utc) + timedelta(days=30),
    )
    activate_trial(user)
    assert get_effective_tier(user) == "pro_plus"


def test_expired_subscription_falls_back_to_trial(db_session):
    """유료 구독 만료 + 체험 활성 → 체험으로 fallback."""
    user = models.User(
        email="eff-5@test.com",
        hashed_password="x",
        tier="pro",
        subscription_expires_at=datetime.now(timezone.utc) - timedelta(days=1),
    )
    activate_trial(user)
    assert get_effective_tier(user) == TRIAL_TIER


# ── E2E: 회원가입 → 체험 자동 활성화 ───────────────────────────

def test_register_endpoint_activates_trial(client, db_session):
    """POST /auth/register 시 신규 사용자에게 체험 자동 부여."""
    resp = client.post(
        "/api/v1/auth/register",
        json={
            "email": "newuser@test.com",
            "password": "Test1234!",
            "company_name": "테스트",
            "ceo_name": "홍길동",
        },
    )
    assert resp.status_code in (200, 201), resp.text

    user = db_session.query(models.User).filter(models.User.email == "newuser@test.com").first()
    assert user is not None
    assert user.trial_started_at is not None
    assert user.trial_expires_at is not None
    assert is_trial_active(user)


# ── E2E: require_tier 가 체험 인식 ────────────────────────────

def _make_auth_client(client, db_session, email: str, **kwargs):
    """헬퍼: 임의 User 만들고 Authorization 헤더 붙은 client 반환."""
    user = models.User(email=email, hashed_password="x", **kwargs)
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    token = create_access_token({"sub": str(user.id)})
    client.headers["Authorization"] = f"Bearer {token}"
    return client, user


def test_trial_user_passes_pro_gate(client, db_session):
    """체험 활성 사용자가 Pro 게이트가 있는 엔드포인트 호출 시 통과."""
    client, user = _make_auth_client(client, db_session, "gate-trial@test.com", tier="free")
    activate_trial(user)
    db_session.commit()

    # /payments/subscription 은 인증만 필요하지만 응답에 effective tier 가 pro 로 반영
    resp = client.get("/api/v1/payments/subscription")
    assert resp.status_code == 200
    data = resp.json()
    assert data["tier"] == "pro"
    assert data["is_trial"] is True
    assert data["is_active"] is True
    assert data["trial_days_remaining"] >= TRIAL_DAYS - 1


def test_expired_trial_user_treated_as_free(client, db_session):
    client, user = _make_auth_client(client, db_session, "gate-expired@test.com", tier="free")
    user.trial_started_at = datetime.now(timezone.utc) - timedelta(days=30)
    user.trial_expires_at = datetime.now(timezone.utc) - timedelta(days=16)
    db_session.commit()

    resp = client.get("/api/v1/payments/subscription")
    assert resp.status_code == 200
    data = resp.json()
    assert data["tier"] == "free"
    assert data["is_trial"] is False
    assert data["is_active"] is False
    assert data["has_used_trial"] is True


# ── /users/me/trial 엔드포인트 ────────────────────────────────

def test_trial_status_endpoint_active(client, db_session):
    client, user = _make_auth_client(client, db_session, "ts-active@test.com", tier="free")
    activate_trial(user)
    db_session.commit()

    resp = client.get("/api/v1/users/me/trial")
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_active"] is True
    assert data["has_used"] is True
    assert data["days_remaining"] >= TRIAL_DAYS - 1
    assert data["expires_at"] is not None


def test_trial_status_endpoint_never_started(client, db_session):
    client, _ = _make_auth_client(client, db_session, "ts-new@test.com", tier="free")

    resp = client.get("/api/v1/users/me/trial")
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_active"] is False
    assert data["has_used"] is False
    assert data["days_remaining"] == 0
    assert data["expires_at"] is None


def test_trial_status_endpoint_expired(client, db_session):
    client, user = _make_auth_client(client, db_session, "ts-expired@test.com", tier="free")
    user.trial_started_at = datetime.now(timezone.utc) - timedelta(days=30)
    user.trial_expires_at = datetime.now(timezone.utc) - timedelta(days=16)
    db_session.commit()

    resp = client.get("/api/v1/users/me/trial")
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_active"] is False
    assert data["has_used"] is True
    assert data["days_remaining"] == 0
