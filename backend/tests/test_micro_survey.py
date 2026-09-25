"""1문항 설문(micro_survey_answered)과 답장형 피드백 요청 메일."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from app.core.config import settings
from app.db import models
from app.services import consent as consent_service
from app.services import mailer, nurture

EVENTS = "/api/v1/growth/events"


@pytest.fixture(autouse=True)
def _clean_events(db_session):
    db_session.query(models.GrowthEvent).filter(
        models.GrowthEvent.event_name == "micro_survey_answered"
    ).delete()
    db_session.commit()
    yield


def _answer(client, q, a, *, detail=None, anon=None):
    meta = {"q": q, "a": a}
    if detail is not None:
        meta["detail"] = detail
    return client.post(EVENTS, json={
        "event_name": "micro_survey_answered",
        "event_id": uuid4().hex,
        "anonymous_id": anon or uuid4().hex,
        "metadata": meta,
    })


def _anonymous(admin_client):
    admin_client.headers.pop("Authorization", None)
    return admin_client


class TestSurveyAnswer:
    def test_answer_recorded_and_one_per_person(self, admin_client):
        anon = uuid4().hex
        token = admin_client.headers["Authorization"]
        c = _anonymous(admin_client)
        first = _answer(c, "visit_purpose", "투찰가·하한선 계산", anon=anon)
        again = _answer(c, "visit_purpose", "그냥 둘러보기", anon=anon)
        other_q = _answer(c, "monthly_bids", "10~29건", anon=anon)
        assert first.status_code == 202 and first.json()["duplicate"] is False
        assert again.json()["duplicate"] is True
        assert other_q.json()["duplicate"] is False

        c.headers["Authorization"] = token
        stats = c.get("/api/v1/admin/growth/micro-survey").json()
        assert stats["questions"]["visit_purpose"]["answers"] == [["투찰가·하한선 계산", 1]]
        assert stats["questions"]["monthly_bids"]["total"] == 1

    def test_detail_text_kept_for_admin(self, admin_client):
        _answer(admin_client, "payment_hesitation", "기타", detail="  연간 결제만 되나요?  ")
        q = admin_client.get("/api/v1/admin/growth/micro-survey").json()["questions"]["payment_hesitation"]
        assert q["details"][0]["detail"] == "연간 결제만 되나요?"
        assert q["details"][0]["user_id"] is not None  # 로그인 응답은 계정으로 이어진다

    @pytest.mark.parametrize("meta", [
        {"q": "made_up", "a": "x"},
        {"q": "visit_purpose", "a": ""},
        {"q": "visit_purpose", "a": "선택지에 없는 답"},
        {"q": "visit_purpose", "a": "기타", "detail": "x" * 301},
        {"q": "visit_purpose", "a": "그냥 둘러보기", "detail": "기타가 아닌데 직접 입력"},
        {"q": "visit_purpose", "a": 3},
        {"q": ["visit_purpose"], "a": "기타"},
    ])
    def test_rejects_bad_input(self, admin_client, meta):
        resp = admin_client.post(EVENTS, json={
            "event_name": "micro_survey_answered", "event_id": uuid4().hex,
            "anonymous_id": uuid4().hex, "metadata": meta,
        })
        assert resp.status_code == 400

    def test_screen_options_match_server_allowlist(self):
        """화면의 선택지 문자열이 서버 허용 목록과 갈라지면 응답이 조용히 400 으로 버려진다."""
        from app.api.v1.endpoints.growth import MICRO_SURVEY_QUESTIONS

        html_dir = Path(__file__).resolve().parents[2] / "infra" / "nginx" / "html"
        pages = {"visit_purpose": "diagnose.html", "monthly_bids": "dashboard.html", "payment_hesitation": "checkout.html"}
        assert set(pages) == set(MICRO_SURVEY_QUESTIONS)
        for q, page in pages.items():
            src = (html_dir / page).read_text(encoding="utf-8")
            assert f"'{q}'" in src
            for answer in MICRO_SURVEY_QUESTIONS[q]:
                assert f"'{answer}'" in src, f"{page} 에 '{answer}' 선택지가 없다"

    def test_admin_only(self, client):
        assert client.get("/api/v1/admin/growth/micro-survey").status_code in (401, 403)


def _user(db_session, *, confirmed):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    user = models.User(email=f"fb-{uuid4().hex[:8]}@company.com", hashed_password="x", company_name="○○전기")
    if confirmed:
        user.marketing_consent = True
        user.marketing_consent_at = now
        user.marketing_confirmed_at = now
        user.consent_text_version = consent_service.CURRENT_VERSION[consent_service.PURPOSE_MARKETING]
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


class TestFeedbackRequest:
    @pytest.fixture
    def sent(self, monkeypatch):
        box = []

        def _fake_send(*, to, subject, text, html=None, headers=None):
            box.append({"to": to, "subject": subject, "text": text})
            return mailer.SendResult(status="sent", provider="ses", message_id="m-1")

        monkeypatch.setattr(settings, "OUTBOUND_EMAIL_ENABLED", True)
        monkeypatch.setattr(nurture.mailer, "send", _fake_send)
        return box

    def test_blocked_without_confirmed_consent(self, admin_client, db_session, sent):
        user = _user(db_session, confirmed=False)
        r = admin_client.post(f"/api/v1/admin/outbound/feedback-request?user_id={user.id}").json()
        assert r["status"] == "skipped" and r["reason"] == "no_consent"
        assert sent == []

    def test_sends_once_as_ad(self, admin_client, db_session, sent):
        user = _user(db_session, confirmed=True)
        first = admin_client.post(f"/api/v1/admin/outbound/feedback-request?user_id={user.id}").json()
        again = admin_client.post(f"/api/v1/admin/outbound/feedback-request?user_id={user.id}").json()
        assert first["status"] == "sent"
        assert again["reason"] == "duplicate"
        assert len(sent) == 1
        assert sent[0]["subject"].startswith("(광고)")
        assert "○○전기 대표님" in sent[0]["text"] and "답장" in sent[0]["text"]

    def test_unknown_user(self, admin_client):
        assert admin_client.post("/api/v1/admin/outbound/feedback-request?user_id=999999").status_code == 404
