"""반송·불만 자동 억제 테스트.

지키려는 사실:
  1) 서명 없는/위조된 SNS 요청으로는 **임의 주소를 발송 금지로 만들 수 없다**(이게 뚫리면
     조용한 서비스 거부가 된다).
  2) 영구 반송·불만은 억제되고, **일시 반송은 억제되지 않는다**(정상 고객 보호).
  3) 억제된 주소에는 광고뿐 아니라 **거래 메일도 나가지 않는다**(계정 평판 보호).
  4) 불만(스팸 신고)은 수신거부 의사로 간주해 동의를 철회하고 증적을 남긴다.
"""
import base64
import json
from datetime import datetime, timezone

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from app.services import consent as consent_service
from app.services import mailer, nurture, sns_verify, suppression

WEBHOOK = "/api/v1/webhooks/ses"
CERT_URL = "https://sns.ap-northeast-2.amazonaws.com/SimpleNotificationService-test.pem"


@pytest.fixture(scope="module")
def signing_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(autouse=True)
def fake_cert(monkeypatch, signing_key):
    """SNS 인증서 조회를 테스트 키의 공개키로 대체(네트워크 없이 서명 경로 전체 검증)."""
    pub_pem = signing_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    monkeypatch.setattr(sns_verify, "_fetch_certificate", lambda url: pub_pem)
    sns_verify._cert_cache.clear()
    yield
    sns_verify._cert_cache.clear()


def _sign(payload: dict, key) -> dict:
    """AWS 규격대로 서명을 붙인다(SignatureVersion 1 = SHA1WithRSA)."""
    body = sns_verify._string_to_sign(payload)
    sig = key.sign(body, padding.PKCS1v15(), hashes.SHA1())
    return {**payload, "Signature": base64.b64encode(sig).decode(), "SignatureVersion": "1"}


def _notification(message: dict, key, **overrides) -> dict:
    payload = {
        "Type": "Notification",
        "MessageId": "mid-1",
        "TopicArn": "arn:aws:sns:ap-northeast-2:612973836152:bideasy-ses-events",
        "Message": json.dumps(message),
        "Timestamp": "2026-07-30T08:00:00.000Z",
        "SigningCertURL": CERT_URL,
    }
    payload.update(overrides)
    return _sign(payload, key)


def _bounce(email: str, btype: str = "Permanent") -> dict:
    return {
        "notificationType": "Bounce",
        "bounce": {
            "bounceType": btype,
            "bounceSubType": "General",
            "bouncedRecipients": [
                {"emailAddress": email, "diagnosticCode": "smtp; 550 5.1.1 user unknown"}
            ],
        },
    }


def _complaint(email: str, feedback: str = "abuse") -> dict:
    return {
        "notificationType": "Complaint",
        "complaint": {
            "complaintFeedbackType": feedback,
            "complainedRecipients": [{"emailAddress": email}],
        },
    }


@pytest.fixture
def clean_suppressions(db_session):
    from app.db import models

    db_session.query(models.EmailSuppression).delete()
    db_session.commit()
    yield
    db_session.query(models.EmailSuppression).delete()
    db_session.commit()


class TestSignatureVerification:
    def test_unsigned_request_is_rejected(self, client, clean_suppressions, db_session):
        payload = {
            "Type": "Notification",
            "MessageId": "x",
            "TopicArn": "arn:aws:sns:ap-northeast-2:1:t",
            "Message": json.dumps(_bounce("victim@company.com")),
            "Timestamp": "2026-07-30T08:00:00.000Z",
            "SigningCertURL": CERT_URL,
        }
        resp = client.post(WEBHOOK, content=json.dumps(payload))
        assert resp.status_code == 403
        # 핵심: 위조 요청으로 남의 주소가 차단되면 안 된다
        assert suppression.is_suppressed(db_session, "victim@company.com") is False

    def test_tampered_message_is_rejected(self, client, signing_key, clean_suppressions, db_session):
        payload = _notification(_bounce("a@company.com"), signing_key)
        payload["Message"] = json.dumps(_bounce("victim2@company.com"))  # 서명 후 본문 교체
        resp = client.post(WEBHOOK, content=json.dumps(payload))
        assert resp.status_code == 403
        assert suppression.is_suppressed(db_session, "victim2@company.com") is False

    def test_foreign_cert_host_is_rejected(self, client, signing_key, clean_suppressions):
        payload = _notification(
            _bounce("a@company.com"), signing_key,
            SigningCertURL="https://evil.example.com/cert.pem",
        )
        # 서명은 유효하지만 인증서 출처가 SNS 가 아니다 → 자작 서명 공격 차단
        assert client.post(WEBHOOK, content=json.dumps(payload)).status_code == 403

    def test_topic_allowlist(self, client, signing_key, monkeypatch, clean_suppressions):
        from app.core.config import settings

        monkeypatch.setattr(settings, "SES_SNS_TOPIC_ARN", "arn:aws:sns:ap-northeast-2:1:other")
        payload = _notification(_bounce("a@company.com"), signing_key)
        assert client.post(WEBHOOK, content=json.dumps(payload)).status_code == 403

    def test_malformed_body(self, client):
        assert client.post(WEBHOOK, content="not json").status_code == 400


class TestBounceHandling:
    def test_permanent_bounce_suppresses(self, client, db_session, signing_key, clean_suppressions):
        payload = _notification(_bounce("hardbounce@company.com"), signing_key)
        resp = client.post(WEBHOOK, content=json.dumps(payload))
        assert resp.status_code == 200 and resp.json()["suppressed"] == 1

        row = suppression.get(db_session, "hardbounce@company.com")
        assert row is not None
        assert row.reason == "bounce" and row.subtype == "Permanent/General"
        assert "550" in (row.detail or "")

    def test_transient_bounce_does_not_suppress(self, client, db_session, signing_key, clean_suppressions):
        payload = _notification(_bounce("soft@company.com", btype="Transient"), signing_key)
        resp = client.post(WEBHOOK, content=json.dumps(payload))
        assert resp.status_code == 200 and resp.json()["transient"] is True
        # 사서함 꽉 참 같은 일시 실패로 고객을 영구히 잃으면 안 된다
        assert suppression.is_suppressed(db_session, "soft@company.com") is False

    def test_repeat_event_is_idempotent(self, client, db_session, signing_key, clean_suppressions):
        payload = _notification(_bounce("dup@company.com"), signing_key)
        client.post(WEBHOOK, content=json.dumps(payload))
        client.post(WEBHOOK, content=json.dumps(payload))
        from app.db import models

        rows = (
            db_session.query(models.EmailSuppression)
            .filter(models.EmailSuppression.email == "dup@company.com")
            .all()
        )
        assert len(rows) == 1 and rows[0].event_count == 2

    def test_case_insensitive(self, client, db_session, signing_key, clean_suppressions):
        client.post(WEBHOOK, content=json.dumps(_notification(_bounce("MiXeD@Company.com"), signing_key)))
        assert suppression.is_suppressed(db_session, "mixed@company.com") is True


class TestComplaintHandling:
    def test_complaint_suppresses_and_withdraws_consent(
        self, client, db_session, signing_key, clean_suppressions
    ):
        from app.db import models

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        lead = models.Lead(
            email="Angry@company.com", region="부산광역시",
            marketing_consent=True, marketing_consent_at=now, marketing_confirmed_at=now,
        )
        db_session.add(lead)
        db_session.commit()

        resp = client.post(WEBHOOK, content=json.dumps(_notification(_complaint("angry@company.com"), signing_key)))
        assert resp.status_code == 200 and resp.json()["suppressed"] == 1

        db_session.refresh(lead)
        assert suppression.is_suppressed(db_session, "angry@company.com") is True
        # 스팸 신고자에게 "동의는 유효하다"고 버티지 않는다
        assert lead.marketing_consent is False
        assert consent_service.can_send_marketing(lead) is False

        rec = (
            db_session.query(models.ConsentRecord)
            .filter(
                models.ConsentRecord.subject_id == lead.id,
                models.ConsentRecord.action == consent_service.ACTION_WITHDRAW,
            )
            .first()
        )
        assert rec is not None and rec.source == "ses_complaint"

    def test_delivery_event_is_noop(self, client, signing_key, clean_suppressions, db_session):
        msg = {"notificationType": "Delivery", "delivery": {"recipients": ["ok@company.com"]}}
        resp = client.post(WEBHOOK, content=json.dumps(_notification(msg, signing_key)))
        assert resp.status_code == 200 and resp.json()["handled"] == "noop"
        assert suppression.is_suppressed(db_session, "ok@company.com") is False


class TestSubscriptionConfirmation:
    def test_auto_confirms(self, client, signing_key, monkeypatch, clean_suppressions):
        called = {}

        class _Resp:
            def raise_for_status(self):
                return None

        def _fake_get(url, timeout=None):
            called["url"] = url
            return _Resp()

        monkeypatch.setattr(sns_verify.httpx, "get", _fake_get)
        payload = _sign(
            {
                "Type": "SubscriptionConfirmation",
                "MessageId": "sub-1",
                "Token": "tok",
                "TopicArn": "arn:aws:sns:ap-northeast-2:1:t",
                "Message": "You have chosen to subscribe",
                "SubscribeURL": "https://sns.ap-northeast-2.amazonaws.com/?Action=ConfirmSubscription",
                "Timestamp": "2026-07-30T08:00:00.000Z",
                "SigningCertURL": CERT_URL,
            },
            signing_key,
        )
        resp = client.post(WEBHOOK, content=json.dumps(payload))
        assert resp.status_code == 200 and resp.json()["handled"] == "subscription_confirmation"
        assert "amazonaws.com" in called["url"]

    def test_rejects_foreign_subscribe_url(self, client, signing_key, monkeypatch, clean_suppressions):
        hits = []
        monkeypatch.setattr(sns_verify.httpx, "get", lambda url, timeout=None: hits.append(url))
        payload = _sign(
            {
                "Type": "SubscriptionConfirmation",
                "MessageId": "sub-2",
                "Token": "tok",
                "TopicArn": "arn:aws:sns:ap-northeast-2:1:t",
                "Message": "m",
                "SubscribeURL": "https://evil.example.com/confirm",
                "Timestamp": "2026-07-30T08:00:00.000Z",
                "SigningCertURL": CERT_URL,
            },
            signing_key,
        )
        resp = client.post(WEBHOOK, content=json.dumps(payload))
        # 서버가 임의 URL 을 대신 긁어주는 통로가 되면 안 된다(SSRF)
        assert resp.status_code == 200 and resp.json()["ok"] is False
        assert hits == []


class TestSendingGate:
    @pytest.fixture
    def captured(self, monkeypatch):
        sent = []
        monkeypatch.setattr(
            nurture.mailer, "send",
            lambda **kw: (sent.append(kw), mailer.SendResult(status="sent", provider="ses", message_id="m"))[1],
        )
        return sent

    def test_suppressed_blocks_marketing_and_transactional(
        self, db_session, captured, clean_suppressions
    ):
        from types import SimpleNamespace
        from app.db import models

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        lead = models.Lead(
            email="blocked@company.com", region="부산광역시",
            marketing_consent=True, marketing_consent_at=now, marketing_confirmed_at=now,
        )
        db_session.add(lead)
        db_session.commit()
        suppression.suppress(db_session, "blocked@company.com", reason=suppression.REASON_BOUNCE)

        ad = nurture.send_marketing(db_session, lead, subject_type="lead", template="lead_welcome")
        assert ad.status == "skipped" and ad.reason == "suppressed"

        # 거래 메일도 막힌다 — 억제는 고객 보호가 아니라 채널(계정 평판) 보호다
        tx = nurture.send_transactional(
            db_session, SimpleNamespace(id=None, email="blocked@company.com"),
            subject_type="user", template="trial_expiry", ctx={"days_left": 3},
        )
        assert tx.status == "skipped" and tx.reason == "suppressed"
        assert captured == []

    def test_release_restores_sending_but_not_consent(self, db_session, captured, clean_suppressions):
        from types import SimpleNamespace

        suppression.suppress(db_session, "back@company.com", reason=suppression.REASON_BOUNCE)
        assert suppression.release(db_session, "back@company.com") is True

        tx = nurture.send_transactional(
            db_session, SimpleNamespace(id=None, email="back@company.com"),
            subject_type="user", template="trial_expiry", ctx={"days_left": 1},
        )
        assert tx.status == "sent" and len(captured) == 1


class TestAdminSuppressionApi:
    def test_requires_admin(self, client):
        assert client.get("/api/v1/admin/outbound/suppressions").status_code in (401, 403)

    def test_list_add_release(self, admin_client, db_session, clean_suppressions):
        add = admin_client.post(
            "/api/v1/admin/outbound/suppressions",
            params={"email": "Manual@Company.com", "detail": "전화로 거부 의사"},
        )
        assert add.status_code == 200 and add.json()["email"] == "manual@company.com"

        listed = admin_client.get("/api/v1/admin/outbound/suppressions", params={"q": "manual"})
        assert listed.status_code == 200 and listed.json()["total"] == 1
        assert listed.json()["items"][0]["reason"] == "manual"

        rel = admin_client.delete(
            "/api/v1/admin/outbound/suppressions", params={"email": "manual@company.com"}
        )
        assert rel.status_code == 200
        assert suppression.is_suppressed(db_session, "manual@company.com") is False
        assert admin_client.delete(
            "/api/v1/admin/outbound/suppressions", params={"email": "manual@company.com"}
        ).status_code == 404
