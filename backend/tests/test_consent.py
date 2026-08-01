"""수신동의 증적 테스트 — 아웃바운드(SES·알림톡) 발송의 법적 전제 검증.

여기서 지키려는 것은 코드 동작이 아니라 **증명 가능성**이다:
  1) 동의 없이 캡처된 연락처는 어떤 경로로도 발송 대상이 되지 않는다.
  2) 동의가 있으면 "언제·어디서·무슨 문구에" 동의했는지 증적이 남는다.
  3) 화면 문구와 서버 정본이 갈라지면 테스트가 깨진다(증적 무결성).
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.services import consent as consent_service

# 정적 웹 페이지(nginx 볼륨) — 저장소 루트 기준
_WEB_DIR = Path(__file__).resolve().parents[2] / "infra" / "nginx" / "html"


@pytest.fixture(autouse=True)
def _isolate_lead_rate_limit(monkeypatch):
    """리드 엔드포인트 레이트리밋을 이 모듈 안에서 격리(로컬 Redis·이전 카운터 공유 금지)."""
    import app.api.v1.endpoints.leads as leads_mod

    leads_mod._ip_call_log.clear()
    monkeypatch.setattr(leads_mod, "_get_redis", lambda: None)
    yield
    leads_mod._ip_call_log.clear()


@pytest.fixture
def notices(db_session):
    from app.db import models

    db_session.query(models.Notice).delete()
    db_session.add(
        models.Notice(
            bid_no="CONSENT-E1",
            title="부산 A초등학교 전기공사",
            basic_price=100000000,
            contract_type="CONSTRUCTION",
            organization="테스트기관",
            region="부산광역시",
            start_date=datetime.now(),
            end_date=datetime.now() + timedelta(days=5),
        )
    )
    db_session.commit()


def _capture_payload(**extra):
    payload = {
        "industry": "전기공사",
        "region": "부산광역시",
        "email": "consent@company.com",
        "nurture_channel": "email",
    }
    payload.update(extra)
    return payload


def _records(db, subject_id, purpose=None):
    from app.db import models

    q = db.query(models.ConsentRecord).filter(
        models.ConsentRecord.subject_type == "lead",
        models.ConsentRecord.subject_id == subject_id,
    )
    if purpose:
        q = q.filter(models.ConsentRecord.purpose == purpose)
    return q.all()


class TestConsentTexts:
    def test_current_versions_exist(self):
        for purpose, version in consent_service.CURRENT_VERSION.items():
            assert version in consent_service.CONSENT_TEXTS[purpose]

    def test_unknown_version_rejected(self):
        with pytest.raises(consent_service.UnknownConsentVersion):
            consent_service.resolve_version(consent_service.PURPOSE_MARKETING, "1999-01-01.v0")

    def test_hash_is_stable_and_version_specific(self):
        h1 = consent_service.text_hash(consent_service.PURPOSE_MARKETING)
        h2 = consent_service.text_hash(consent_service.PURPOSE_MARKETING)
        assert h1 == h2 and len(h1) == 64
        signup_hash = consent_service.text_hash(
            consent_service.PURPOSE_MARKETING, consent_service.SIGNUP_MARKETING_VERSION
        )
        assert signup_hash != h1  # 문구가 다르면 지문도 달라야 증적이 의미를 가진다


class TestConsentTextDrift:
    """화면 문구 = 서버 정본. 한쪽만 고치면 증적(해시)이 거짓이 되므로 여기서 막는다."""

    def _html(self, name):
        path = _WEB_DIR / name
        if not path.exists():
            pytest.skip(f"정적 웹 파일 없음: {path}")
        return path.read_text(encoding="utf-8")

    def test_diagnose_page_matches_canonical_text(self):
        html = self._html("diagnose.html")
        version = consent_service.CURRENT_VERSION[consent_service.PURPOSE_PRIVACY]
        assert f'data-consent-version="{version}"' in html
        for purpose in (consent_service.PURPOSE_PRIVACY, consent_service.PURPOSE_MARKETING):
            for line in consent_service.consent_text(purpose).splitlines():
                assert line.strip() in html, f"화면에 없는 동의 문구 줄: {line}"

    def test_signup_page_matches_canonical_text(self):
        html = self._html("signup.html")
        version = consent_service.SIGNUP_MARKETING_VERSION
        assert f'data-consent-version="{version}"' in html
        text = consent_service.consent_text(consent_service.PURPOSE_MARKETING, version)
        for line in text.splitlines():
            assert line.strip() in html, f"화면에 없는 동의 문구 줄: {line}"


class TestConsentTextsEndpoint:
    def test_public_canonical_texts(self, client):
        resp = client.get("/api/v1/leads/consent-texts")
        assert resp.status_code == 200
        data = resp.json()
        assert data["privacy"]["required"] is True
        assert data["marketing"]["required"] is False
        assert data["marketing"]["text"] == consent_service.consent_text(
            consent_service.PURPOSE_MARKETING
        )


class TestCaptureConsent:
    def test_explicit_refusal_blocks_capture(self, client, notices):
        resp = client.post("/api/v1/leads/capture", json=_capture_payload(privacy_consent=False))
        assert resp.status_code == 400
        assert "개인정보" in resp.json()["detail"]

    def test_unknown_version_asks_refresh(self, client, notices):
        resp = client.post(
            "/api/v1/leads/capture",
            json=_capture_payload(privacy_consent=True, consent_version="1999-01-01.v0"),
        )
        assert resp.status_code == 400
        assert "새로고침" in resp.json()["detail"]

    def test_privacy_only_is_not_sendable(self, client, db_session, notices):
        from app.db import models

        resp = client.post("/api/v1/leads/capture", json=_capture_payload(privacy_consent=True))
        assert resp.status_code == 200
        assert resp.json()["marketing_consent"] is False

        lead = db_session.get(models.Lead, resp.json()["lead_id"])
        assert lead.privacy_consent is True
        assert lead.privacy_consent_at is not None
        assert lead.marketing_consent is False
        # 광고 발송 금지 — 동의한 것은 "결과 제공"까지다
        assert consent_service.can_send_marketing(lead) is False
        assert len(_records(db_session, lead.id, consent_service.PURPOSE_MARKETING)) == 0
        assert len(_records(db_session, lead.id, consent_service.PURPOSE_PRIVACY)) == 1

    def test_marketing_consent_records_evidence(self, client, db_session, notices):
        from app.db import models

        resp = client.post(
            "/api/v1/leads/capture",
            json=_capture_payload(
                privacy_consent=True,
                marketing_consent=True,
                consent_version=consent_service.CURRENT_VERSION[consent_service.PURPOSE_MARKETING],
            ),
            headers={"X-Forwarded-For": "1.2.3.4", "User-Agent": "pytest-agent/1.0"},
        )
        assert resp.status_code == 200
        assert resp.json()["marketing_consent"] is True

        lead = db_session.get(models.Lead, resp.json()["lead_id"])
        assert lead.marketing_consent is True
        assert lead.marketing_consent_at is not None
        assert lead.marketing_withdrawn_at is None
        assert lead.consent_ip == "1.2.3.4"
        assert "pytest-agent" in (lead.consent_user_agent or "")

        # 더블 옵트인: 이 폼은 인증이 없어 제출자가 그 주소의 주인이라는 증거가 없다.
        # 동의 증적은 남기되 주소 소유자가 확인 링크를 누르기 전까지는 발송 대상이 아니다.
        assert lead.marketing_confirmed_at is None
        assert consent_service.can_send_marketing(lead) is False
        assert resp.json()["confirm_pending"] is True

        consent_service.confirm_marketing(db_session, lead, subject_type="lead", source="test")
        db_session.commit()
        assert lead.marketing_confirmed_at is not None
        assert consent_service.can_send_marketing(lead) is True

        rec = _records(db_session, lead.id, consent_service.PURPOSE_MARKETING)[0]
        assert rec.action == consent_service.ACTION_GRANT
        assert rec.source == "web_diagnose"
        assert rec.ip == "1.2.3.4"
        assert rec.email == "consent@company.com"
        assert rec.text_hash == consent_service.text_hash(
            consent_service.PURPOSE_MARKETING, rec.text_version
        )

    def test_marketing_without_privacy_ui_is_ignored(self, client, db_session, notices):
        """구버전 페이지가 marketing 만 보내는 경우 — 필수 동의 증적이 없으면 발송 불가."""
        from app.db import models

        resp = client.post("/api/v1/leads/capture", json=_capture_payload(marketing_consent=True))
        assert resp.status_code == 200
        lead = db_session.get(models.Lead, resp.json()["lead_id"])
        assert lead.marketing_consent is False
        assert consent_service.can_send_marketing(lead) is False
        assert _records(db_session, lead.id) == []

    def test_legacy_page_capture_still_works(self, client, db_session, notices):
        """동의 UI 가 없던 캐시된 페이지 — 캡처는 되지만 광고 발송 대상은 아니다."""
        from app.db import models

        resp = client.post("/api/v1/leads/capture", json=_capture_payload())
        assert resp.status_code == 200
        lead = db_session.get(models.Lead, resp.json()["lead_id"])
        assert lead.privacy_consent is False
        assert consent_service.can_send_marketing(lead) is False


class TestSendablePolicy:
    def _lead(self, db, **kw):
        from app.db import models

        lead = models.Lead(email="policy@company.com", region="부산광역시", **kw)
        db.add(lead)
        db.commit()
        db.refresh(lead)
        return lead

    def test_withdrawal_stops_sending_and_leaves_evidence(self, db_session):
        from app.db import models

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        lead = self._lead(
            db_session,
            marketing_consent=True,
            marketing_consent_at=now,
            marketing_confirmed_at=now,
            consent_text_version=consent_service.CURRENT_VERSION[consent_service.PURPOSE_MARKETING],
        )
        assert consent_service.can_send_marketing(lead) is True

        consent_service.withdraw_marketing(
            db_session, lead, subject_type="lead", source="email_unsub", note="수신거부 링크"
        )
        db_session.commit()

        assert lead.marketing_consent is False
        assert lead.marketing_withdrawn_at is not None
        assert lead.nurture_status == "unsub"
        assert consent_service.can_send_marketing(lead) is False

        rec = (
            db_session.query(models.ConsentRecord)
            .filter(
                models.ConsentRecord.subject_id == lead.id,
                models.ConsentRecord.action == consent_service.ACTION_WITHDRAW,
            )
            .first()
        )
        assert rec is not None and rec.source == "email_unsub"

    def test_stale_consent_expires_after_two_years(self, db_session):
        old = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
            days=consent_service.REVALIDATE_DAYS + 1
        )
        lead = self._lead(
            db_session, marketing_consent=True, marketing_consent_at=old, marketing_confirmed_at=old
        )
        # 정보통신망법 제50조 제8항 — 2년마다 확인. 확인 없으면 발송 중단.
        assert consent_service.can_send_marketing(lead) is False

    def test_sql_filter_matches_python_judgement(self, db_session):
        """발송 대상 쿼리(sendable_filter)와 단건 판정(can_send_marketing)이 어긋나면 사고가 난다."""
        from app.db import models

        db_session.query(models.Lead).delete()
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        old = now - timedelta(days=consent_service.REVALIDATE_DAYS + 1)
        self._lead(db_session, marketing_consent=True, marketing_consent_at=now, marketing_confirmed_at=now)
        self._lead(db_session, marketing_consent=True, marketing_consent_at=old, marketing_confirmed_at=old)
        self._lead(db_session, marketing_consent=False)
        self._lead(
            db_session,
            marketing_consent=True,
            marketing_consent_at=now,
            marketing_confirmed_at=now,
            marketing_withdrawn_at=now,
        )

        sendable = (
            db_session.query(models.Lead)
            .filter(consent_service.sendable_filter(models.Lead))
            .all()
        )
        assert len(sendable) == 1
        for lead in db_session.query(models.Lead).all():
            assert consent_service.can_send_marketing(lead) == (lead in sendable)


class TestSignupConsent:
    def test_signup_without_consent_is_not_sendable(self, client, db_session):
        from app.db import models

        resp = client.post(
            "/api/v1/auth/register",
            json={"email": "nomkt@company.com", "password": "password123"},
        )
        assert resp.status_code == 200
        user = db_session.query(models.User).filter(models.User.email == "nomkt@company.com").first()
        assert user.marketing_consent is False
        assert consent_service.can_send_marketing(user) is False

    def test_signup_with_consent_records_evidence(self, client, db_session):
        from app.db import models

        resp = client.post(
            "/api/v1/auth/register",
            json={
                "email": "withmkt@company.com",
                "password": "password123",
                "marketing_consent": True,
                "consent_version": consent_service.SIGNUP_MARKETING_VERSION,
            },
        )
        assert resp.status_code == 200
        user = db_session.query(models.User).filter(models.User.email == "withmkt@company.com").first()
        assert user.marketing_consent is True

        # 더블 옵트인: 가입 폼도 이메일 소유를 확인하지 않는다(소셜 로그인만 검증된
        # 이메일을 준다). 동의 증적은 남기되 확인 링크를 누르기 전까지는 발송 대상이 아니다.
        assert user.marketing_confirmed_at is None
        assert consent_service.can_send_marketing(user) is False

        consent_service.confirm_marketing(db_session, user, subject_type="user", source="test")
        db_session.commit()
        assert consent_service.can_send_marketing(user) is True

        rec = (
            db_session.query(models.ConsentRecord)
            .filter(
                models.ConsentRecord.subject_type == "user",
                models.ConsentRecord.subject_id == user.id,
            )
            .first()
        )
        assert rec is not None
        assert rec.source == "web_signup"
        assert rec.text_version == consent_service.SIGNUP_MARKETING_VERSION

    def test_signup_with_unknown_version_does_not_record(self, client, db_session):
        """캐시된 구버전 폼 — 가입은 되지만 임의 문구로 동의를 날조하지 않는다."""
        from app.db import models

        resp = client.post(
            "/api/v1/auth/register",
            json={
                "email": "badver@company.com",
                "password": "password123",
                "marketing_consent": True,
                "consent_version": "1999-01-01.v0",
            },
        )
        assert resp.status_code == 200
        user = db_session.query(models.User).filter(models.User.email == "badver@company.com").first()
        assert user.marketing_consent is False
        assert (
            db_session.query(models.ConsentRecord)
            .filter(
                models.ConsentRecord.subject_type == "user",
                models.ConsentRecord.subject_id == user.id,
            )
            .count()
            == 0
        )


class TestAdminConsentEndpoints:
    def test_requires_admin(self, client):
        assert client.get("/api/v1/admin/consents").status_code in (401, 403)
        assert client.get("/api/v1/admin/consents/summary").status_code in (401, 403)

    def test_search_and_summary(self, admin_client, db_session, notices):
        admin_client.post(
            "/api/v1/leads/capture",
            json=_capture_payload(privacy_consent=True, marketing_consent=True),
        )

        found = admin_client.get("/api/v1/admin/consents", params={"q": "consent@company.com"})
        assert found.status_code == 200
        items = found.json()["items"]
        assert {i["purpose"] for i in items} == {"privacy", "marketing"}

        summary = admin_client.get("/api/v1/admin/consents/summary")
        assert summary.status_code == 200
        body = summary.json()
        assert body["leads"]["sendable"] >= 1
        assert body["revalidate_days"] == consent_service.REVALIDATE_DAYS
