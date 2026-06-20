"""유입 귀속(attribution) — 가입 시 UTM/referrer 저장 + admin 채널 집계."""
import pytest
from fastapi.testclient import TestClient

from app.db import models
from app.db.session import get_db
from app.core.security import create_access_token, get_password_hash
from main import app


@pytest.fixture
def client(db_session):
    def _override():
        yield db_session

    app.dependency_overrides[get_db] = _override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_register_stores_attribution(client, db_session):
    r = client.post(
        "/api/v1/auth/register",
        json={
            "email": "attr1@test.com",
            "password": "Passw0rd!",
            "signup_source": "naver",
            "signup_medium": "organic",
            "signup_campaign": "blog-doksojohang",
            "signup_referrer": "https://search.naver.com/",
        },
    )
    assert r.status_code == 200, r.text
    u = db_session.query(models.User).filter(models.User.email == "attr1@test.com").first()
    assert u.signup_source == "naver"
    assert u.signup_medium == "organic"
    assert u.signup_campaign == "blog-doksojohang"
    assert u.signup_referrer == "https://search.naver.com/"


def test_register_without_attribution_is_null(client, db_session):
    r = client.post(
        "/api/v1/auth/register",
        json={"email": "attr2@test.com", "password": "Passw0rd!"},
    )
    assert r.status_code == 200, r.text
    u = db_session.query(models.User).filter(models.User.email == "attr2@test.com").first()
    assert u.signup_source is None
    assert u.signup_referrer is None


def test_long_values_truncated_not_rejected(client, db_session):
    long_ref = "https://x.com/?q=" + "a" * 500
    r = client.post(
        "/api/v1/auth/register",
        json={
            "email": "attr3@test.com",
            "password": "Passw0rd!",
            "signup_source": "s" * 200,
            "signup_referrer": long_ref,
        },
    )
    assert r.status_code == 200, r.text  # 긴 값이 가입을 막지 않아야 함
    u = db_session.query(models.User).filter(models.User.email == "attr3@test.com").first()
    assert len(u.signup_source) <= 120
    assert len(u.signup_referrer) <= 300


def test_admin_attribution_stats(client, db_session):
    admin = models.User(
        email="attr-admin@test.com",
        hashed_password=get_password_hash("Passw0rd!"),
        is_admin=True,
        tier="free",
    )
    db_session.add(admin)
    db_session.add(models.User(email="c1@test.com", hashed_password=get_password_hash("x"), tier="pro", signup_source="naver"))
    db_session.add(models.User(email="c2@test.com", hashed_password=get_password_hash("x"), tier="free", signup_source="naver"))
    db_session.commit()
    db_session.refresh(admin)

    token = create_access_token({"sub": str(admin.id), "tv": admin.token_version or 0})
    r = client.get(
        "/api/v1/admin/stats/attribution",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    naver = next((c for c in data["channels"] if c["source"] == "naver"), None)
    assert naver is not None
    assert naver["signups"] >= 2
    assert naver["paid"] >= 1  # tier=pro 1건
