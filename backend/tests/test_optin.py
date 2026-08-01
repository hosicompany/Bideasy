"""더블 옵트인 공용 엔드포인트 — 리드·회원 모두 확인 후에만 광고 대상이 된다.

지키려는 사실:
  1) 가입 폼도 이메일 소유를 확인하지 않으므로, 체크박스만으로는 광고가 나가지 않는다.
  2) 확인은 POST 로만 된다(GET 프리페치로 대신 눌리지 않는다).
  3) 옵트인 토큰과 수신거부 토큰은 **서로 쓸 수 없다**(용도 분리).
  4) 철회한 사람은 옛 확인 링크로 되살아나지 않는다.
"""
import pytest

from app.core.signed_token import make_token
from app.services import consent as consent_service
from app.services import mailer, nurture


@pytest.fixture
def captured_mail(monkeypatch):
    sent = []

    def _fake_send(*, to, subject, text, html, headers=None):
        sent.append({"to": to, "subject": subject, "text": text, "headers": headers or {}})
        return mailer.SendResult(status="sent", provider="fake", message_id="m-1")

    monkeypatch.setattr(mailer, "send", _fake_send)
    return sent


def _register(client, email="optin-user@company.com", consent=True):
    return client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": "password123",
            "marketing_consent": consent,
            "consent_version": consent_service.SIGNUP_MARKETING_VERSION,
        },
    )


def _user(db, email):
    from app.db import models

    return db.query(models.User).filter(models.User.email == email).first()


class TestSignupOptin:
    def test_signup_sends_no_ad(self, client, db_session, captured_mail):
        """가입 시 나가는 건 전부 **거래** 메일이다 — 체험 시작 안내 + 수신 확인 요청.

        확인 전이므로 광고는 한 통도 나가면 안 된다.
        """
        from app.services import email_templates

        resp = _register(client, "sig1@company.com")
        assert resp.status_code == 200

        assert len(captured_mail) == 2
        subjects = [m["subject"] for m in captured_mail]
        assert any("체험" in s for s in subjects)        # D0 웰컴(거래)
        assert any("확인" in s for s in subjects)        # 옵트인 확인(거래)
        for m in captured_mail:
            assert m["to"] == "sig1@company.com"
            assert not m["subject"].startswith(email_templates.AD_PREFIX)
            assert "List-Unsubscribe" not in m["headers"]

    def test_unconfirmed_user_is_not_sendable(self, client, db_session, captured_mail):
        """확인 전에는 광고 발송 대상이 아니다 — SQL 필터에서도 빠진다."""
        from app.db import models

        _register(client, "sig2@company.com")
        user = _user(db_session, "sig2@company.com")

        assert consent_service.can_send_marketing(user) is False
        sendable = (
            db_session.query(models.User)
            .filter(consent_service.sendable_filter(models.User))
            .filter(models.User.email == "sig2@company.com")
            .first()
        )
        assert sendable is None

    def test_post_optin_makes_user_sendable(self, client, db_session, captured_mail):
        _register(client, "sig3@company.com")
        user = _user(db_session, "sig3@company.com")
        token = make_token(nurture.OPTIN_PURPOSE, "user", user.id)

        resp = client.post("/api/v1/optin", params={"token": token})
        assert resp.status_code == 200 and resp.json()["already"] is False

        db_session.refresh(user)
        assert consent_service.can_send_marketing(user) is True

    def test_get_status_does_not_confirm(self, client, db_session, captured_mail):
        """메일 스캐너의 링크 프리페치가 사용자 대신 확인해 버리면 안 된다."""
        _register(client, "sig4@company.com")
        user = _user(db_session, "sig4@company.com")
        token = make_token(nurture.OPTIN_PURPOSE, "user", user.id)

        status = client.get("/api/v1/optin/status", params={"token": token})
        assert status.status_code == 200 and status.json()["confirmed"] is False

        db_session.refresh(user)
        assert consent_service.can_send_marketing(user) is False

    def test_no_consent_means_no_confirmation_mail(self, client, db_session, captured_mail):
        """수신동의를 안 하면 확인 메일을 보내지 않는다 — 무관한 메일은 그 자체가 스팸.

        단 체험 시작 안내(거래)는 동의와 무관하게 나간다. 서비스 이용 안내이기 때문이다.
        """
        _register(client, "sig5@company.com", consent=False)

        subjects = [m["subject"] for m in captured_mail]
        assert any("체험" in s for s in subjects)          # D0 웰컴은 나간다
        assert not any("확인" in s for s in subjects)      # 확인 요청은 나가지 않는다

    def test_signup_survives_mail_failure(self, client, db_session, monkeypatch):
        """확인 메일이 터져도 가입은 성공한다 — 메일 한 통 때문에 가입을 잃지 않는다."""
        def _boom(**kwargs):
            raise mailer.MailerError("SES down")

        monkeypatch.setattr(mailer, "send", _boom)

        resp = _register(client, "sig6@company.com")
        assert resp.status_code == 200
        assert _user(db_session, "sig6@company.com") is not None


class TestOptinTokenSafety:
    def test_unsub_token_cannot_confirm(self, client, db_session, captured_mail):
        """수신거부 토큰으로 옵트인을 할 수 없다 — 용도가 분리돼 있다.

        섞이면 유출된 해지 링크로 **재구독**까지 가능해진다(정반대 행위인데도).
        """
        _register(client, "tok1@company.com")
        user = _user(db_session, "tok1@company.com")
        unsub_token = nurture.unsubscribe_token("user", user.id)

        resp = client.post("/api/v1/optin", params={"token": unsub_token})
        assert resp.status_code == 400

        db_session.refresh(user)
        assert consent_service.can_send_marketing(user) is False

    def test_optin_token_cannot_unsubscribe(self, client, db_session, captured_mail):
        """반대 방향도 막힌다."""
        _register(client, "tok2@company.com")
        user = _user(db_session, "tok2@company.com")
        optin_token = make_token(nurture.OPTIN_PURPOSE, "user", user.id)

        assert client.post("/api/v1/unsubscribe", params={"token": optin_token}).status_code == 400

    def test_forged_token_rejected(self, client):
        assert client.post("/api/v1/optin", params={"token": "forged.sig"}).status_code == 400
        assert client.get("/api/v1/optin/status", params={"token": "forged.sig"}).status_code == 400

    def test_withdrawn_user_cannot_be_revived(self, client, db_session, captured_mail):
        """철회한 사람이 옛 확인 링크를 눌러도 되살아나지 않는다."""
        _register(client, "tok3@company.com")
        user = _user(db_session, "tok3@company.com")
        token = make_token(nurture.OPTIN_PURPOSE, "user", user.id)

        consent_service.withdraw_marketing(db_session, user, subject_type="user", source="test")
        db_session.commit()

        assert client.post("/api/v1/optin", params={"token": token}).status_code == 400
        db_session.refresh(user)
        assert consent_service.can_send_marketing(user) is False
