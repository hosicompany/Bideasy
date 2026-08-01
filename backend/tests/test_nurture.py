"""아웃바운드 발송 파이프라인 테스트 — 게이트·멱등·수신거부.

지키려는 사실:
  1) 동의 없는 대상에게는 광고 메일이 **나가지 않는다**(그리고 그 사실이 원장에 남는다).
  2) 광고 메일에는 "(광고)" 표기와 수신거부 수단이 **빠질 수 없다**.
  3) 같은 메일이 두 번 나가지 않는다(멱등), 실패하면 재시도 여지는 남는다.
  4) 수신거부 링크 한 번으로 즉시 끊기고, GET 프리페치로는 끊기지 않는다.
"""
from datetime import datetime, timezone

import pytest

from app.core.config import settings
from app.core.signed_token import InvalidSignedToken, make_token, parse_token
from app.services import consent as consent_service
from app.services import email_templates, mailer, nurture


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


@pytest.fixture
def consented_lead(db_session):
    """광고 발송이 가능한 상태의 리드(동의 + 시각 증적)."""
    from app.db import models

    now = _utcnow()
    lead = models.Lead(
        email="send@company.com",
        region="부산광역시",
        industry="전기공사",
        matched_count=12,
        privacy_consent=True,
        privacy_consent_at=now,
        marketing_consent=True,
        marketing_consent_at=now,
        marketing_confirmed_at=now,
        consent_text_version=consent_service.CURRENT_VERSION[consent_service.PURPOSE_MARKETING],
    )
    db_session.add(lead)
    db_session.commit()
    db_session.refresh(lead)
    return lead


@pytest.fixture
def plain_lead(db_session):
    """동의 없는 리드 — 광고 발송 대상이 아니다."""
    from app.db import models

    lead = models.Lead(email="noconsent@company.com", region="부산광역시", industry="전기공사")
    db_session.add(lead)
    db_session.commit()
    db_session.refresh(lead)
    return lead


@pytest.fixture
def captured_mail(monkeypatch):
    """실제 전송 대신 호출 인자를 붙잡는다(SES 호출 없이 파이프라인 전체 검증)."""
    sent = []

    def _fake_send(*, to, subject, text, html=None, headers=None):
        sent.append({"to": to, "subject": subject, "text": text, "html": html, "headers": headers or {}})
        return mailer.SendResult(status="sent", provider="ses", message_id="msg-1")

    monkeypatch.setattr(nurture.mailer, "send", _fake_send)
    return sent


class TestSignedToken:
    def test_roundtrip(self):
        token = make_token("unsub", "lead", 42)
        assert parse_token("unsub", token) == ("lead", 42)

    def test_tampered_payload_rejected(self):
        token = make_token("unsub", "lead", 42)
        payload, _, sig = token.rpartition(".")
        forged = make_token("unsub", "lead", 43).split(".")[0] + "." + sig
        assert forged != token
        with pytest.raises(InvalidSignedToken):
            parse_token("unsub", forged)

    def test_purpose_is_not_interchangeable(self):
        """다른 용도로 발급된 토큰은 수신거부에 쓸 수 없다."""
        token = make_token("other", "lead", 42)
        with pytest.raises(InvalidSignedToken):
            parse_token("unsub", token)

    def test_garbage_rejected(self):
        for bad in ("", None, "abc", "a.b.c"):
            with pytest.raises(InvalidSignedToken):
                parse_token("unsub", bad)


class TestTemplates:
    def test_marketing_subject_is_prefixed_and_footer_has_optout(self):
        rendered = email_templates.render(
            "lead_welcome",
            {"region": "부산광역시", "industry": "전기공사", "matched_count": 12},
            unsubscribe_url="https://bideasy.kr/unsubscribe?t=X",
        )
        assert rendered.subject.startswith(email_templates.AD_PREFIX)  # (광고) 표기 = 법정 의무
        assert "unsubscribe?t=X" in rendered.text and "unsubscribe?t=X" in rendered.html
        assert email_templates.SENDER_CONTACT in rendered.text

    def test_transactional_has_no_ad_prefix(self):
        rendered = email_templates.render("trial_expiry", {"days_left": 3})
        assert not rendered.subject.startswith(email_templates.AD_PREFIX)
        assert "수신거부" not in rendered.text  # 거래 고지에 광고성 해지 안내를 붙이지 않는다

    def test_unknown_template(self):
        with pytest.raises(email_templates.UnknownTemplate):
            email_templates.render("nope")


class TestMailer:
    def test_disabled_is_dry_run(self, monkeypatch):
        monkeypatch.setattr(settings, "OUTBOUND_EMAIL_ENABLED", False)
        result = mailer.send(to="a@b.com", subject="제목", text="본문")
        assert result.status == "dry_run" and result.provider == "none"

    def test_raw_message_carries_custom_headers(self):
        msg = mailer.build_message(
            to="a@b.com", subject="제목", text="본문",
            headers={"List-Unsubscribe": "<https://x/unsub>"},
        )
        assert msg["List-Unsubscribe"] == "<https://x/unsub>"
        assert msg["To"] == "a@b.com"


class TestMarketingGate:
    def test_no_consent_is_skipped_not_sent(self, db_session, plain_lead, captured_mail):
        row = nurture.send_marketing(
            db_session, plain_lead, subject_type="lead", template="lead_welcome"
        )
        assert row.status == "skipped" and row.reason == "no_consent"
        assert captured_mail == []           # 실제로 나가지 않았다
        assert row.dedupe_key is None        # 동의를 받으면 나중에 보낼 수 있어야 한다

    def test_consented_lead_receives_ad_mail(self, db_session, consented_lead, captured_mail):
        row = nurture.send_marketing(
            db_session, consented_lead, subject_type="lead", template="lead_welcome",
            ctx={"region": "부산광역시", "industry": "전기공사", "matched_count": 12},
        )
        assert row.status == "sent" and row.provider_message_id == "msg-1"

        mail = captured_mail[0]
        assert mail["to"] == "send@company.com"
        assert mail["subject"].startswith(email_templates.AD_PREFIX)
        # 원클릭 수신거부(RFC 8058) — 스팸 신고 대신 해지를 누르게 하는 장치
        assert "List-Unsubscribe" in mail["headers"]
        assert mail["headers"]["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
        assert "/unsubscribe?t=" in mail["text"]

    def test_withdrawn_lead_is_skipped(self, db_session, consented_lead, captured_mail):
        consent_service.withdraw_marketing(
            db_session, consented_lead, subject_type="lead", source="email_unsub"
        )
        db_session.commit()
        row = nurture.send_marketing(
            db_session, consented_lead, subject_type="lead", template="lead_welcome"
        )
        assert row.status == "skipped" and row.reason == "no_consent"
        assert captured_mail == []

    def test_transactional_ignores_consent(self, db_session, plain_lead, captured_mail):
        row = nurture.send_transactional(
            db_session, plain_lead, subject_type="lead", template="trial_expiry",
            ctx={"days_left": 3},
        )
        assert row.status == "sent"
        assert not captured_mail[0]["subject"].startswith(email_templates.AD_PREFIX)

    def test_category_mismatch_raises(self, db_session, consented_lead):
        with pytest.raises(ValueError):
            nurture.send_marketing(
                db_session, consented_lead, subject_type="lead", template="trial_expiry"
            )

    def test_missing_email_is_skipped(self, db_session, captured_mail):
        from app.db import models

        lead = models.Lead(phone="010-1234-5678", region="부산광역시")
        db_session.add(lead)
        db_session.commit()
        row = nurture.send_marketing(db_session, lead, subject_type="lead", template="lead_welcome")
        assert row.status == "skipped" and row.reason == "no_email"


class TestIdempotency:
    def test_same_dedupe_key_sends_once(self, db_session, consented_lead, captured_mail):
        key = f"lead_welcome:lead:{consented_lead.id}"
        first = nurture.send_marketing(
            db_session, consented_lead, subject_type="lead", template="lead_welcome", dedupe_key=key
        )
        second = nurture.send_marketing(
            db_session, consented_lead, subject_type="lead", template="lead_welcome", dedupe_key=key
        )
        assert first.status == "sent"
        assert second.status == "skipped" and second.reason == "duplicate"
        assert len(captured_mail) == 1

    def test_failure_releases_key_for_retry(self, db_session, consented_lead, monkeypatch):
        def _boom(**kwargs):
            raise mailer.MailerError("throttled")

        monkeypatch.setattr(nurture.mailer, "send", _boom)
        key = f"lead_welcome:lead:{consented_lead.id}:retry"
        row = nurture.send_marketing(
            db_session, consented_lead, subject_type="lead", template="lead_welcome", dedupe_key=key
        )
        assert row.status == "failed" and "throttled" in (row.error or "")
        # 키를 붙잡고 있으면 영구히 재시도 불가가 된다 → 실패 시 해제되어야 한다
        assert row.dedupe_key is None


class TestUnsubscribeEndpoint:
    def test_status_does_not_change_state(self, client, db_session, consented_lead):
        token = nurture.unsubscribe_token("lead", consented_lead.id)
        resp = client.get("/api/v1/unsubscribe/status", params={"token": token})
        assert resp.status_code == 200
        body = resp.json()
        assert body["unsubscribed"] is False
        assert body["email"].endswith("@company.com") and "*" in body["email"]  # 부분 마스킹
        db_session.refresh(consented_lead)
        assert consented_lead.marketing_consent is True  # GET 프리페치로 해지되지 않는다

    def test_post_unsubscribes_and_is_idempotent(self, client, db_session, consented_lead):
        from app.db import models

        token = nurture.unsubscribe_token("lead", consented_lead.id)
        first = client.post("/api/v1/unsubscribe", params={"token": token})
        assert first.status_code == 200 and first.json()["already"] is False

        db_session.refresh(consented_lead)
        assert consented_lead.marketing_consent is False
        assert consented_lead.marketing_withdrawn_at is not None
        assert consent_service.can_send_marketing(consented_lead) is False

        # 철회 증적이 남아야 분쟁 시 "즉시 처리했다"를 증명할 수 있다
        rec = (
            db_session.query(models.ConsentRecord)
            .filter(
                models.ConsentRecord.subject_id == consented_lead.id,
                models.ConsentRecord.action == consent_service.ACTION_WITHDRAW,
            )
            .first()
        )
        assert rec is not None and rec.source == "email_unsub"

        second = client.post("/api/v1/unsubscribe", params={"token": token})
        assert second.status_code == 200 and second.json()["already"] is True

    def test_invalid_token_rejected(self, client):
        assert client.post("/api/v1/unsubscribe", params={"token": "forged.token"}).status_code == 400


class TestUnsubscribeResultNotice:
    """수신거부 처리 결과 통지 — 정보통신망법 제50조가 요구하는 법정 고지.

    보내도 되는 메일이 아니라 **보내야 하는** 메일이다. 동시에 방금 광고를 거부한
    사람에게 가는 메일이라, 광고성 문구가 한 줄이라도 섞이면 거부 의사를 무시한
    광고 발송이 된다.
    """

    @pytest.fixture(autouse=True)
    def _isolate(self, db_session):
        """테스트 DB 는 세션 스코프 파일이라 원장·억제가 누적된다 — 매 테스트 초기화."""
        from app.db import models

        def _wipe():
            for model in (models.OutboundMessage, models.EmailSuppression):
                db_session.query(model).delete()
            db_session.commit()

        _wipe()
        yield
        _wipe()

    def test_unsubscribe_sends_result_notice(self, client, db_session, consented_lead, captured_mail):
        token = nurture.unsubscribe_token("lead", consented_lead.id)
        client.post("/api/v1/unsubscribe", params={"token": token})

        assert len(captured_mail) == 1
        mail = captured_mail[0]
        assert mail["to"] == consented_lead.email
        assert "수신거부 처리 결과" in mail["subject"]

    def test_notice_is_not_an_ad(self, client, db_session, consented_lead, captured_mail):
        """통지에 광고 표기·재동의 유도·수신거부 링크가 붙으면 안 된다."""
        token = nurture.unsubscribe_token("lead", consented_lead.id)
        client.post("/api/v1/unsubscribe", params={"token": token})

        mail = captured_mail[0]
        assert not mail["subject"].startswith(email_templates.AD_PREFIX)
        # 거래 메일이므로 원클릭 수신거부 헤더를 붙이지 않는다(이미 거부한 사람이다)
        assert "List-Unsubscribe" not in mail["headers"]
        assert "수신거부하실 수 있어요" not in mail["text"]
        # 재동의 유도가 섞이면 그 순간 광고물이 된다
        for lure in ("할인", "다시 받", "구독", "혜택"):
            assert lure not in mail["text"]

    def test_notice_records_processing_time(self, client, db_session, consented_lead, captured_mail):
        """처리 일시를 함께 알린다 — '언제 처리했는가'가 통지의 핵심이다."""
        token = nurture.unsubscribe_token("lead", consented_lead.id)
        client.post("/api/v1/unsubscribe", params={"token": token})

        db_session.refresh(consented_lead)
        assert "(KST)" in captured_mail[0]["text"]
        assert consented_lead.email in captured_mail[0]["text"]

    def test_repeat_unsubscribe_does_not_renotify(self, client, db_session, consented_lead, captured_mail):
        """이미 해지된 상태에서 다시 눌러도 통지는 한 번 — 재통지는 그 자체로 스팸이다."""
        token = nurture.unsubscribe_token("lead", consented_lead.id)
        client.post("/api/v1/unsubscribe", params={"token": token})
        client.post("/api/v1/unsubscribe", params={"token": token})

        assert len(captured_mail) == 1

    def test_unsubscribe_survives_notice_failure(self, client, db_session, consented_lead, monkeypatch):
        """통지 발송이 터져도 **해지는 성공한다** — 해지 실패가 훨씬 나쁘다."""
        def _boom(**kwargs):
            raise mailer.MailerError("SES down")

        monkeypatch.setattr(mailer, "send", _boom)

        resp = client.post(
            "/api/v1/unsubscribe",
            params={"token": nurture.unsubscribe_token("lead", consented_lead.id)},
        )
        assert resp.status_code == 200 and resp.json()["already"] is False

        db_session.refresh(consented_lead)
        assert consented_lead.marketing_consent is False
        assert consent_service.can_send_marketing(consented_lead) is False

    def test_suppressed_address_is_not_notified(self, client, db_session, consented_lead, captured_mail):
        """억제된 주소(반송·불만)에는 통지도 나가지 않는다 — 채널을 지키는 쪽이 우선."""
        from app.db import models
        from app.services import suppression

        suppression.suppress(db_session, consented_lead.email, reason=suppression.REASON_COMPLAINT)

        client.post(
            "/api/v1/unsubscribe",
            params={"token": nurture.unsubscribe_token("lead", consented_lead.id)},
        )

        assert captured_mail == []
        db_session.refresh(consented_lead)
        assert consented_lead.marketing_consent is False      # 해지는 그대로 처리됨
        # 막힌 사실이 원장에 남아 "통지를 시도했다"는 증적이 된다
        row = (
            db_session.query(models.OutboundMessage)
            .filter(models.OutboundMessage.template == "unsub_result")
            .one()
        )
        assert row.status == "skipped" and row.reason == "suppressed"
        assert client.get("/api/v1/unsubscribe/status", params={"token": "x"}).status_code == 400

    def test_user_subject_supported(self, client, db_session):
        from app.db import models

        now = _utcnow()
        user = models.User(
            email="unsub-user@company.com", hashed_password="x",
            marketing_consent=True, marketing_consent_at=now, marketing_confirmed_at=now,
        )
        db_session.add(user)
        db_session.commit()
        token = nurture.unsubscribe_token("user", user.id)
        assert client.post("/api/v1/unsubscribe", params={"token": token}).status_code == 200
        db_session.refresh(user)
        assert user.marketing_consent is False


class TestAdminOutbound:
    def test_requires_admin(self, client):
        assert client.get("/api/v1/admin/outbound").status_code in (401, 403)
        assert client.get("/api/v1/admin/outbound/preview", params={"template": "lead_welcome"}).status_code in (401, 403)

    def test_preview_renders_without_sending(self, admin_client, captured_mail):
        resp = admin_client.get("/api/v1/admin/outbound/preview", params={"template": "lead_welcome"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["category"] == "marketing"
        assert body["subject"].startswith(email_templates.AD_PREFIX)
        assert captured_mail == []

    def test_preview_unknown_template_404(self, admin_client):
        resp = admin_client.get("/api/v1/admin/outbound/preview", params={"template": "nope"})
        assert resp.status_code == 404

    def test_log_reports_killswitch_and_counts(self, admin_client, db_session, plain_lead):
        nurture.send_marketing(db_session, plain_lead, subject_type="lead", template="lead_welcome")
        resp = admin_client.get("/api/v1/admin/outbound")
        assert resp.status_code == 200
        body = resp.json()
        assert body["outbound_enabled"] is False   # 기본은 꺼짐(오발송 방지)
        assert any(r["reason"] == "no_consent" for r in body["by_reason"])

    def test_test_send_respects_gate(self, admin_client):
        """관리자 본인도 미동의면 광고 템플릿은 skipped — 게이트가 살아 있다는 증거."""
        resp = admin_client.post("/api/v1/admin/outbound/test-send", params={"template": "lead_welcome"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "skipped"
        assert resp.json()["reason"] == "no_consent"
