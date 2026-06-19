"""소셜 로그인 보안 회귀 테스트 — OAuth state(CSRF) + 미검증 이메일 병합 차단."""
from app.api.v1.endpoints.auth import _find_or_create_social_user
from app.core.security import create_oauth_state, verify_oauth_state
from app.db import models


# ─── OAuth state (CSRF) ──────────────────────────────────

def test_oauth_state_roundtrip():
    state = create_oauth_state()
    assert verify_oauth_state(state) is True


def test_oauth_state_rejects_forged():
    assert verify_oauth_state("not-a-real-state") is False
    assert verify_oauth_state("") is False
    assert verify_oauth_state(None) is False


def test_oauth_state_rejects_expired():
    expired = create_oauth_state(expires_minutes=-1)  # 이미 만료
    assert verify_oauth_state(expired) is False


def test_naver_callback_requires_state(client):
    # state 없이 호출 시 FastAPI 가 422 (필수 쿼리 누락)
    r = client.get("/api/v1/auth/callback/naver?code=x", follow_redirects=False)
    assert r.status_code == 422


def test_kakao_callback_rejects_invalid_state(client):
    r = client.get("/api/v1/auth/callback/kakao?code=x&state=forged", follow_redirects=False)
    assert r.status_code in (302, 303, 307)
    assert "error=invalid_state" in r.headers["location"]


# ─── 미검증 이메일 병합 차단 ──────────────────────────────

def test_unverified_email_does_not_merge_existing_account(db_session):
    """비밀번호로 가입한 기존 계정을, 같은 이메일의 '미검증' 소셜 로그인이 탈취하지 못한다."""
    victim = models.User(email="victim@example.com", hashed_password="hashed-pw", tier="free")
    db_session.add(victim)
    db_session.commit()
    victim_id = victim.id

    user = _find_or_create_social_user(
        db_session, provider="kakao", social_id="kakao-attacker-1",
        email="victim@example.com", profile_image=None, email_verified=False,
    )
    # 기존 계정에 병합되지 않고 별도 계정이 생성되어야 함
    assert user.id != victim_id
    assert user.social_provider == "kakao"
    # 기존 계정은 소셜 정보가 오염되지 않음
    db_session.expire_all()
    v = db_session.query(models.User).filter(models.User.id == victim_id).first()
    assert v.social_provider is None
    assert v.hashed_password == "hashed-pw"


def test_verified_email_merges_existing_account(db_session):
    """검증된 이메일이면 기존 계정에 소셜 식별자를 연결(정상 병합)."""
    existing = models.User(email="owner@example.com", hashed_password="pw", tier="free")
    db_session.add(existing)
    db_session.commit()
    existing_id = existing.id

    user = _find_or_create_social_user(
        db_session, provider="naver", social_id="naver-owner-1",
        email="owner@example.com", profile_image=None, email_verified=True,
    )
    assert user.id == existing_id
    assert user.social_provider == "naver"
    assert user.social_id == "naver-owner-1"
