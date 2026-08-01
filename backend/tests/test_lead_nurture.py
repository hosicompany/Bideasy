"""리드 육성 시퀀스 테스트 — 웰컴 1통 + 주기 신규 매칭.

지키려는 사실:
  1) 진단 캡처에서 동의를 남긴 리드에게만 웰컴이 실제로 나간다(미동의는 나가지 않는다).
  2) 웰컴 발송이 실패해도 **리드 캡처는 성공한다**(연락처를 잃지 않는다).
  3) 주기 발송은 `sendable_filter` 를 통과한 리드에게만, **신규** 공고가 있을 때만 나간다.
  4) 같은 주에 두 번 나가지 않는다(멱등), 전환된 리드에게는 나가지 않는다.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.services import consent as consent_service
from app.services import email_templates, mailer


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class _SessionWrapper:
    """태스크가 자기 세션을 close 해도 테스트 세션은 살려둔다."""

    def __init__(self, real):
        self._real = real

    def __getattr__(self, name):
        if name == "close":
            return lambda: None
        return getattr(self._real, name)


def _run_task(db_session):
    """태스크를 테스트 세션 위에서 실행."""
    from app.tasks.nurture_tasks import send_lead_matches

    with patch("app.tasks.nurture_tasks.SessionLocal", lambda: _SessionWrapper(db_session)):
        return send_lead_matches()


@pytest.fixture(autouse=True)
def _isolate(db_session):
    """테스트 DB 는 세션 스코프 파일이라 리드·공고·원장이 누적된다 — 매 테스트 초기화."""
    from app.db import models

    def _wipe():
        for model in (models.OutboundMessage, models.ConsentRecord, models.Lead, models.Notice):
            db_session.query(model).delete()
        db_session.commit()

    _wipe()
    yield
    _wipe()


@pytest.fixture
def captured_mail(monkeypatch):
    """실제 SES 호출 없이 '무엇이 나갔는지'만 잡는다."""
    sent = []

    def _fake_send(*, to, subject, text, html, headers=None):
        sent.append({"to": to, "subject": subject, "text": text, "html": html,
                     "headers": headers or {}})
        return mailer.SendResult(status="sent", provider="fake", message_id="m-1")

    monkeypatch.setattr(mailer, "send", _fake_send)
    return sent


def _mk_notice(db, bid_no, title, region, *, start_days_ago=0, end_days=5):
    from app.db import models

    n = models.Notice(
        bid_no=bid_no,
        title=title,
        basic_price=100000000,
        contract_type="CONSTRUCTION",
        organization="테스트기관",
        region=region,
        start_date=datetime.now() - timedelta(days=start_days_ago),
        end_date=datetime.now() + timedelta(days=end_days),
    )
    db.add(n)
    db.commit()
    return n


@pytest.fixture
def busan_new_notice(db_session):
    return _mk_notice(db_session, "NUR-E1", "부산 전기공사 신규 공고", "부산광역시", start_days_ago=1)


def _consented_lead(db, *, email="lead@company.com", status="new", confirmed=None):
    from app.db import models

    now = confirmed or _utcnow()
    lead = models.Lead(
        email=email,
        region="부산광역시",
        industry="전기공사",
        matched_count=3,
        nurture_status=status,
        privacy_consent=True,
        privacy_consent_at=now,
        marketing_consent=True,
        marketing_consent_at=now,
        marketing_confirmed_at=now,
        consent_text_version=consent_service.CURRENT_VERSION[consent_service.PURPOSE_MARKETING],
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)
    return lead


class TestWelcomeOnCapture:
    def _capture_body(self, **over):
        body = {
            "industry": "전기공사",
            "region": "부산광역시",
            "email": "welcome@company.com",
            "privacy_consent": True,
            "marketing_consent": True,
        }
        body.update(over)
        return body

    def test_consented_capture_sends_welcome(self, client, db_session, busan_new_notice, captured_mail):
        """동의한 캡처 → 웰컴이 실제로 나가고 '(광고)' 표기가 붙는다."""
        resp = client.post("/api/v1/leads/capture", json=self._capture_body())
        assert resp.status_code == 200

        assert len(captured_mail) == 1
        mail = captured_mail[0]
        assert mail["to"] == "welcome@company.com"
        assert mail["subject"].startswith(email_templates.AD_PREFIX)
        # 광고 메일에는 원클릭 수신거부 헤더가 반드시 붙는다(RFC 8058)
        assert "List-Unsubscribe" in mail["headers"]

    def test_no_consent_capture_does_not_send(self, client, db_session, busan_new_notice, captured_mail):
        """수신동의를 안 한 리드에게는 웰컴이 나가지 않는다(원장에는 사유가 남는다)."""
        from app.db import models

        resp = client.post(
            "/api/v1/leads/capture",
            json=self._capture_body(email="noad@company.com", marketing_consent=False),
        )
        assert resp.status_code == 200
        assert captured_mail == []

        row = (
            db_session.query(models.OutboundMessage)
            .filter(models.OutboundMessage.email == "noad@company.com")
            .one()
        )
        assert row.status == "skipped"
        assert row.reason == "no_consent"

    def test_capture_survives_send_failure(self, client, db_session, busan_new_notice, monkeypatch):
        """발송이 터져도 리드 캡처는 성공한다 — 메일 한 통 때문에 연락처를 잃지 않는다."""
        from app.db import models

        def _boom(**kwargs):
            raise mailer.MailerError("SES down")

        monkeypatch.setattr(mailer, "send", _boom)

        resp = client.post("/api/v1/leads/capture", json=self._capture_body(email="boom@company.com"))
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        assert (
            db_session.query(models.Lead).filter(models.Lead.email == "boom@company.com").one()
        ) is not None

    def test_welcome_is_idempotent_per_lead(self, client, db_session, busan_new_notice, captured_mail):
        """같은 리드에게 웰컴은 한 번만 — 재제출해도 두 통 가지 않는다."""
        from app.api.v1.endpoints import leads as leads_mod
        from app.db import models

        resp = client.post("/api/v1/leads/capture", json=self._capture_body(email="once@company.com"))
        lead = db_session.query(models.Lead).filter(models.Lead.id == resp.json()["lead_id"]).one()

        leads_mod._send_welcome(db_session, lead, 3)   # 같은 리드로 재시도
        assert len(captured_mail) == 1


class TestLeadMatchesTask:
    def test_sends_to_consented_lead_with_new_notices(self, db_session, busan_new_notice, captured_mail):
        lead = _consented_lead(db_session)
        result = _run_task(db_session)

        assert result["sent"] == 1
        assert len(captured_mail) == 1
        assert captured_mail[0]["to"] == lead.email
        assert captured_mail[0]["subject"].startswith(email_templates.AD_PREFIX)
        # 낙찰 예측 금지 — 본문이 자격 판정까지만 말하는지
        assert "예측하지는 않아요" in captured_mail[0]["text"]

    def test_skips_lead_without_consent(self, db_session, busan_new_notice, captured_mail):
        """동의 없는 리드는 대상 쿼리에서 아예 빠진다(발송 시도조차 없다)."""
        from app.db import models

        db_session.add(models.Lead(email="plain@company.com", region="부산광역시", industry="전기공사"))
        db_session.commit()

        result = _run_task(db_session)
        assert result["leads_checked"] == 0
        assert captured_mail == []

    def test_skips_expired_consent(self, db_session, busan_new_notice, captured_mail):
        """2년 재확인(§50⑧)을 넘긴 동의는 발송 대상이 아니다."""
        old = _utcnow() - timedelta(days=consent_service.REVALIDATE_DAYS + 1)
        _consented_lead(db_session, email="stale@company.com", confirmed=old)

        result = _run_task(db_session)
        assert result["leads_checked"] == 0
        assert captured_mail == []

    def test_skips_converted_lead(self, db_session, busan_new_notice, captured_mail):
        """가입 전환된 리드에게는 보내지 않는다(회원 알림과 중복)."""
        _consented_lead(db_session, email="conv@company.com", status="converted")

        result = _run_task(db_session)
        assert result["leads_checked"] == 0
        assert captured_mail == []

    def test_no_new_notices_means_no_mail(self, db_session, captured_mail):
        """조건에 맞는 **신규** 공고가 없으면 보내지 않는다 — 빈 메일은 스팸이다."""
        from app.tasks.nurture_tasks import NEW_WINDOW_DAYS

        # 활성이지만 윈도 밖(오래된) 공고만 존재
        _mk_notice(
            db_session, "OLD-E1", "부산 전기공사 오래된 공고", "부산광역시",
            start_days_ago=NEW_WINDOW_DAYS + 3, end_days=5,
        )
        _consented_lead(db_session, email="nomatch@company.com")

        result = _run_task(db_session)
        assert result["sent"] == 0
        assert result["skipped_no_match"] == 1
        assert captured_mail == []

    def test_same_week_runs_once(self, db_session, busan_new_notice, captured_mail):
        """같은 주에 태스크가 두 번 돌아도 메일은 한 통이다(멱등)."""
        _consented_lead(db_session, email="weekly@company.com")

        first = _run_task(db_session)
        second = _run_task(db_session)

        assert first["sent"] == 1
        assert second["sent"] == 0
        assert second["blocked"] == 1     # duplicate 로 차단
        assert len(captured_mail) == 1
