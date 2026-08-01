"""체험 라이프사이클 시퀀스 — 광고/거래 분리가 이 시퀀스의 전부다.

지키려는 사실:
  1) **만료 고지는 전원에게**(거래) — 미동의자가 "체험이 끝난다"를 못 받으면 안 된다.
  2) **할인 안내는 동의자에게만**(광고) — 미동의자에게 나가면 위법 발송이다.
  3) 온보딩 3종(D1·D3·D7)은 전부 광고라 확인까지 마친 회원에게만.
  4) 회원 1명의 실패가 배치를 죽이지 않는다.
  5) 윈백 금액은 상수에서 파생된다 — 가격 개편 때 메일이 거짓말하지 않도록.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.schemas import subscription
from app.services import email_templates, mailer


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class _SessionWrapper:
    def __init__(self, real):
        self._real = real

    def __getattr__(self, name):
        if name == "close":
            return lambda: None
        return getattr(self._real, name)


@pytest.fixture
def captured_mail(monkeypatch):
    sent = []

    def _fake_send(*, to, subject, text, html, headers=None):
        sent.append({"to": to, "subject": subject, "text": text, "headers": headers or {}})
        return mailer.SendResult(status="sent", provider="fake", message_id="m-1")

    monkeypatch.setattr(mailer, "send", _fake_send)
    return sent


@pytest.fixture(autouse=True)
def _isolate(db_session):
    """테스트 DB 는 세션 스코프 파일이라 회원·원장이 누적된다.

    회원까지 지우는 이유: 배치 태스크는 **조건에 맞는 전원**을 훑으므로, 다른 테스트가
    남긴 체험 회원이 섞이면 발송 건수가 어긋난다(자식 테이블부터 지운다).
    """
    from app.db import models

    def _wipe():
        for model in (models.OutboundMessage, models.Notification, models.ConsentRecord,
                      models.Favorite, models.UserBid, models.PointTransaction,
                      models.User):
            db_session.query(model).delete()
        db_session.commit()

    _wipe()
    yield
    _wipe()


def _trial_user(db, email, *, days_left=None, started_days_ago=0, consented=False, confirmed=False):
    """체험 중인 회원. days_left 를 주면 만료 시각을 그만큼 뒤로 잡는다."""
    from app.db import models

    now = _utcnow()
    u = models.User(
        email=email,
        hashed_password="x",
        tier="free",
        trial_started_at=now - timedelta(days=started_days_ago),
        trial_expires_at=(now + timedelta(days=days_left)) if days_left is not None else None,
    )
    if consented:
        u.marketing_consent = True
        u.marketing_consent_at = now
        u.marketing_confirmed_at = now if confirmed else None
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _run_expiry(db_session):
    from app.tasks.trial_tasks import send_expiry_reminders

    with patch("app.tasks.trial_tasks.SessionLocal", lambda: _SessionWrapper(db_session)):
        return send_expiry_reminders()


def _run_onboarding(db_session):
    from app.tasks.trial_tasks import send_onboarding_sequence

    with patch("app.tasks.trial_tasks.SessionLocal", lambda: _SessionWrapper(db_session)):
        return send_onboarding_sequence()


class TestExpiryIsTransactional:
    def test_unconsented_user_still_gets_expiry_notice(self, db_session, captured_mail):
        """미동의자도 만료 고지는 받는다 — 거래 안내이기 때문이다."""
        _trial_user(db_session, "noconsent@company.com", days_left=3)

        result = _run_expiry(db_session)

        assert result["3d"] == 1
        assert len(captured_mail) == 1
        assert not captured_mail[0]["subject"].startswith(email_templates.AD_PREFIX)
        assert "체험" in captured_mail[0]["subject"]

    def test_expiry_notice_has_no_discount(self, db_session, captured_mail):
        """만료 고지에 할인이 섞이면 그 메일 전체가 광고물이 된다."""
        _trial_user(db_session, "plain@company.com", days_left=1)
        _run_expiry(db_session)

        text = captured_mail[0]["text"]
        for ad_word in ("할인", "50%", "반값"):
            assert ad_word not in text


class TestWinbackIsMarketing:
    def test_unconsented_user_gets_no_discount_mail(self, db_session, captured_mail):
        """할인 안내는 광고 — 미동의자에게는 나가지 않는다(원장에는 사유가 남는다)."""
        from app.db import models

        _trial_user(db_session, "expired-noc@company.com", days_left=-1)

        result = _run_expiry(db_session)
        assert result["expired"] == 1
        assert captured_mail == []

        row = (
            db_session.query(models.OutboundMessage)
            .filter(models.OutboundMessage.template == "trial_winback")
            .one()
        )
        assert row.status == "skipped" and row.reason == "no_consent"

    def test_consented_user_gets_discount_mail(self, db_session, captured_mail):
        _trial_user(db_session, "expired-ok@company.com", days_left=-1,
                    consented=True, confirmed=True)

        _run_expiry(db_session)

        assert len(captured_mail) == 1
        mail = captured_mail[0]
        assert mail["subject"].startswith(email_templates.AD_PREFIX)
        assert "List-Unsubscribe" in mail["headers"]      # 광고엔 원클릭 해지가 필수

    def test_winback_price_comes_from_constants(self, db_session, captured_mail):
        """메일 속 금액은 상수에서 파생된다 — 가격 개편 때 조용히 거짓말하지 않도록."""
        _trial_user(db_session, "price@company.com", days_left=-1,
                    consented=True, confirmed=True)
        _run_expiry(db_session)

        expected = "{:,}원".format(
            subscription.MONTHLY_PRICES[subscription.TIER_PRO]
            * (100 - subscription.WINBACK_DISCOUNT_PCT) // 100
        )
        assert expected in captured_mail[0]["text"]
        assert str(subscription.WINBACK_GRACE_DAYS) in captured_mail[0]["text"]


class TestOnboardingSequence:
    def test_unconfirmed_user_gets_nothing(self, db_session, captured_mail):
        """동의는 했지만 확인 전인 회원은 온보딩 광고 대상이 아니다."""
        _trial_user(db_session, "pending@company.com", started_days_ago=3,
                    consented=True, confirmed=False)

        result = _run_onboarding(db_session)

        assert result["checked"] == 0
        assert captured_mail == []

    def test_d3_sends_extension_guide(self, db_session, captured_mail):
        _trial_user(db_session, "d3@company.com", started_days_ago=3,
                    consented=True, confirmed=True)

        result = _run_onboarding(db_session)

        assert result["d3"] == 1
        assert captured_mail[0]["subject"].startswith(email_templates.AD_PREFIX)
        assert "나라장터" in captured_mail[0]["subject"]

    def test_d7_reports_only_real_usage(self, db_session, captured_mail):
        """사용 기록이 없으면 없다고 말한다 — 지어낸 성과는 신뢰를 깎는다."""
        _trial_user(db_session, "d7@company.com", started_days_ago=7,
                    consented=True, confirmed=True)

        result = _run_onboarding(db_session)

        assert result["d7"] == 1
        assert "아직 확인해 보신 공고가 없네요" in captured_mail[0]["text"]

    def test_off_schedule_day_sends_nothing(self, db_session, captured_mail):
        """D2·D5 처럼 예정에 없는 날엔 아무것도 보내지 않는다."""
        _trial_user(db_session, "d5@company.com", started_days_ago=5,
                    consented=True, confirmed=True)

        result = _run_onboarding(db_session)

        assert result["checked"] == 1
        assert (result["d1"], result["d3"], result["d7"]) == (0, 0, 0)
        assert captured_mail == []

    def test_one_failure_does_not_kill_batch(self, db_session, captured_mail, monkeypatch):
        """회원 1명의 실패가 나머지를 막지 않는다."""
        _trial_user(db_session, "boom@company.com", started_days_ago=3,
                    consented=True, confirmed=True)
        _trial_user(db_session, "fine@company.com", started_days_ago=3,
                    consented=True, confirmed=True)

        real_send = mailer.send
        calls = {"n": 0}

        def _flaky(**kwargs):
            calls["n"] += 1
            if kwargs.get("to") == "boom@company.com":
                raise mailer.MailerError("SES down")
            return real_send(**kwargs)

        monkeypatch.setattr(mailer, "send", _flaky)

        result = _run_onboarding(db_session)

        assert result["checked"] == 2
        assert calls["n"] == 2                    # 둘 다 시도됐다
        assert result["d3"] == 2                  # 실패도 건너뛰고 계속 진행


class TestTrialWelcome:
    def test_welcome_prompts_profile_when_empty(self, client, db_session, captured_mail):
        """프로필이 비면 자격 판정이 '판정 불가'라, 그 사실을 알리는 건 기능 설명이다."""
        client.post(
            "/api/v1/auth/register",
            json={"email": "welc@company.com", "password": "password123"},
        )
        welcome = [m for m in captured_mail if "체험" in m["subject"]]
        assert len(welcome) == 1
        assert "면허·지역을 넣으시면" in welcome[0]["text"]
        assert not welcome[0]["subject"].startswith(email_templates.AD_PREFIX)

    def test_welcome_has_no_purchase_pitch(self, client, db_session, captured_mail):
        """거래 메일이므로 구매 권유·할인이 없어야 한다."""
        client.post(
            "/api/v1/auth/register",
            json={"email": "welc2@company.com", "password": "password123"},
        )
        text = [m for m in captured_mail if "체험" in m["subject"]][0]["text"]
        for ad_word in ("할인", "결제하시면", "반값"):
            assert ad_word not in text
