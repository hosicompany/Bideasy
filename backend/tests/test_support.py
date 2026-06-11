"""고객 챗봇 (/support) 테스트 — OpenAI 모킹."""
import pytest
from fastapi.testclient import TestClient

from app.db import models
from app.db.session import get_db
from app.core.security import create_access_token
from main import app
import app.api.v1.endpoints.support as support_mod


@pytest.fixture
def anon_client(db_session):
    def _override():
        yield db_session
    app.dependency_overrides[get_db] = _override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _mock_llm(monkeypatch):
    monkeypatch.setattr(support_mod, "_ask_llm", lambda messages: "테스트 답변입니다.")


def test_chat_logs_and_answers(anon_client, db_session):
    r = anon_client.post("/api/v1/support/chat", json={"message": "요금제 알려줘", "session_id": "sess-test-1"})
    assert r.status_code == 200, r.text
    assert r.json()["answer"] == "테스트 답변입니다."
    msgs = db_session.query(models.SupportMessage).filter(models.SupportMessage.session_id == "sess-test-1").all()
    assert len(msgs) == 2
    assert {m.role for m in msgs} == {"user", "assistant"}


def test_chat_empty_rejected(anon_client):
    assert anon_client.post("/api/v1/support/chat", json={"message": "   "}).status_code == 400


def test_ticket_created(anon_client, db_session):
    r = anon_client.post("/api/v1/support/ticket", json={"message": "환불 문의요", "email": "a@b.com"})
    assert r.status_code == 200
    t = db_session.query(models.SupportTicket).filter(models.SupportTicket.email == "a@b.com").first()
    assert t is not None and t.status == "open"


def test_tickets_admin_only(anon_client, db_session):
    anon_client.post("/api/v1/support/ticket", json={"message": "문의2"})
    admin = db_session.query(models.User).filter(models.User.email == "t-admin-sup@test.com").first()
    if not admin:
        admin = models.User(email="t-admin-sup@test.com", hashed_password="x", is_admin=True)
        db_session.add(admin); db_session.commit(); db_session.refresh(admin)
    tok = create_access_token({"sub": str(admin.id)})
    r = anon_client.get("/api/v1/support/tickets", headers={"Authorization": "Bearer " + tok})
    assert r.status_code == 200 and isinstance(r.json(), list)

    user = db_session.query(models.User).filter(models.User.email == "t-user-sup@test.com").first()
    if not user:
        user = models.User(email="t-user-sup@test.com", hashed_password="x", is_admin=False)
        db_session.add(user); db_session.commit(); db_session.refresh(user)
    tok2 = create_access_token({"sub": str(user.id)})
    r2 = anon_client.get("/api/v1/support/tickets", headers={"Authorization": "Bearer " + tok2})
    assert r2.status_code == 403


def test_chat_rate_limit(anon_client, monkeypatch):
    monkeypatch.setattr(support_mod, "SESSION_DAILY_CAP", 2)
    sid = "sess-rate"
    assert anon_client.post("/api/v1/support/chat", json={"message": "1", "session_id": sid}).status_code == 200
    assert anon_client.post("/api/v1/support/chat", json={"message": "2", "session_id": sid}).status_code == 200
    a3 = anon_client.post("/api/v1/support/chat", json={"message": "3", "session_id": sid})
    assert a3.status_code == 200 and a3.json().get("limited") is True
