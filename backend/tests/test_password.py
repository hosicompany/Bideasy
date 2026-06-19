"""비밀번호 변경 (PUT /users/me/password) 테스트."""
import pytest
from fastapi.testclient import TestClient

from app.db import models
from app.db.session import get_db
from app.core.security import create_access_token, get_password_hash, verify_password
from main import app

_EMAIL = "test-pwchange@test.com"
_PW = "OldPass123!"


@pytest.fixture
def pw_client(db_session):
    """실제 해시 비번을 가진 사용자로 인증된 client (매 테스트 비번 초기화)."""
    user = db_session.query(models.User).filter(models.User.email == _EMAIL).first()
    if not user:
        user = models.User(email=_EMAIL, hashed_password=get_password_hash(_PW), tier="free")
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)
    else:
        user.hashed_password = get_password_hash(_PW)
        user.social_provider = None
        user.token_version = 0  # 비번 변경 테스트가 token_version 을 올리므로 매 테스트 초기화
        db_session.commit()

    token = create_access_token({"sub": str(user.id), "tv": user.token_version or 0})

    def _override():
        yield db_session

    app.dependency_overrides[get_db] = _override
    with TestClient(app) as c:
        c.headers["Authorization"] = f"Bearer {token}"
        yield c
    app.dependency_overrides.clear()


def _user(db):
    return db.query(models.User).filter(models.User.email == _EMAIL).first()


def test_change_password_success(pw_client, db_session):
    r = pw_client.put("/api/v1/users/me/password", json={"current_password": _PW, "new_password": "NewPass456!"})
    assert r.status_code == 200, r.text
    db_session.expire_all()
    u = _user(db_session)
    assert verify_password("NewPass456!", u.hashed_password)
    assert not verify_password(_PW, u.hashed_password)


def test_change_password_invalidates_old_token(pw_client, db_session):
    """비밀번호 변경 시 기존 토큰이 무효화되고, 응답의 새 토큰은 유효해야 한다."""
    old_auth = pw_client.headers["Authorization"]
    r = pw_client.put("/api/v1/users/me/password", json={"current_password": _PW, "new_password": "NewPass456!"})
    assert r.status_code == 200, r.text
    new_token = r.json().get("access_token")
    assert new_token, "응답에 새 access_token 이 있어야 함"

    # 기존 토큰으로는 보호 엔드포인트 접근이 거부되어야 함 (token_version 증가로 무효화)
    r_old = pw_client.get("/api/v1/users/me", headers={"Authorization": old_auth})
    assert r_old.status_code == 401

    # 새 토큰으로는 접근 가능해야 함
    r_new = pw_client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {new_token}"})
    assert r_new.status_code == 200


def test_change_password_wrong_current(pw_client):
    r = pw_client.put("/api/v1/users/me/password", json={"current_password": "WrongPass1!", "new_password": "NewPass456!"})
    assert r.status_code == 400


def test_change_password_too_short(pw_client):
    r = pw_client.put("/api/v1/users/me/password", json={"current_password": _PW, "new_password": "short1"})
    assert r.status_code == 400


def test_change_password_same_as_current(pw_client):
    r = pw_client.put("/api/v1/users/me/password", json={"current_password": _PW, "new_password": _PW})
    assert r.status_code == 400


def test_change_password_social_only_rejected(db_session):
    """소셜 전용 계정(비번 없음)은 변경 불가."""
    u = db_session.query(models.User).filter(models.User.email == "social-only@test.com").first()
    if not u:
        u = models.User(email="social-only@test.com", hashed_password=None, social_provider="kakao", social_id="k1", tier="free")
        db_session.add(u)
        db_session.commit()
        db_session.refresh(u)
    token = create_access_token({"sub": str(u.id)})

    def _override():
        yield db_session

    app.dependency_overrides[get_db] = _override
    with TestClient(app) as c:
        c.headers["Authorization"] = f"Bearer {token}"
        r = c.put("/api/v1/users/me/password", json={"current_password": "x", "new_password": "NewPass456!"})
    app.dependency_overrides.clear()
    assert r.status_code == 400
