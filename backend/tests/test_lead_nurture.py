"""리드 육성 시퀀스 테스트 — 더블 옵트인 → 웰컴 → 주기 신규 매칭.

지키려는 사실:
  1) 캡처만으로는 **광고가 나가지 않는다.** 인증 없는 공개 폼이므로 주소 소유자가
     확인 링크를 눌러야 발송 대상이 된다(제3자 주소로 광고를 쏘지 않는다).
  2) 확인은 GET 프리페치로 되지 않고 POST 로만 된다(메일 스캐너 오확인 방지).
  3) 발송이 실패해도 **리드 캡처는 성공한다**(연락처를 잃지 않는다).
  4) 멱등의 주체는 행이 아니라 **수신자**다 — 같은 사람이 재진단해도 중복 발송이 없다.
  5) 리드 1건의 데이터 결함이 주간 배치 전체를 죽이지 않는다.
  6) 주기 발송은 `sendable_filter` 통과 + **신규** 공고가 있을 때만, 같은 주엔 한 번만.
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


def _optin_token(lead_id: int) -> str:
    from app.core.signed_token import make_token
    from app.services.nurture import OPTIN_PURPOSE

    return make_token(OPTIN_PURPOSE, "lead", lead_id)


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


def _consented_lead(db, *, email="lead@company.com", status="new", confirmed=None,
                    created_at=None, region="부산광역시", industry="전기공사"):
    """더블 옵트인까지 마친 리드(= 광고 발송 대상).

    `created_at` 기본값을 과거로 두는 이유: 배치는 리드 생성 이후 올라온 공고만
    '새 공고'로 보므로(웰컴이 이미 보여준 것과 중복 방지), 방금 만든 리드는 어떤
    공고와도 매칭되지 않는다.
    """
    from app.db import models

    now = confirmed or _utcnow()
    lead = models.Lead(
        email=email,
        region=region,
        industry=industry,
        matched_count=3,
        nurture_status=status,
        created_at=created_at or (_utcnow() - timedelta(days=30)),
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

    def test_capture_sends_confirmation_not_ad(self, client, db_session, busan_new_notice, captured_mail):
        """캡처만으로는 광고가 나가지 않는다 — 나가는 건 '확인 요청'(거래) 1통뿐."""
        resp = client.post("/api/v1/leads/capture", json=self._capture_body())
        assert resp.status_code == 200
        assert resp.json()["confirm_pending"] is True

        assert len(captured_mail) == 1
        mail = captured_mail[0]
        assert mail["to"] == "welcome@company.com"
        # 광고 표기가 **없어야** 한다 — 있으면 미확인 주소로 광고를 보낸 것이 된다.
        assert not mail["subject"].startswith(email_templates.AD_PREFIX)
        assert "확인" in mail["subject"]
        # 확인 메일에 공고 목록·권유가 섞이면 그 순간 광고물이 된다.
        assert busan_new_notice.title not in mail["text"]

    def test_third_party_address_gets_no_ad(self, client, db_session, busan_new_notice, captured_mail):
        """남의 주소를 적어 제출해도 그 주소로 광고는 가지 않는다(확인 전까지)."""
        from app.db import models

        client.post("/api/v1/leads/capture", json=self._capture_body(email="victim@other.co.kr"))

        lead = db_session.query(models.Lead).filter(models.Lead.email == "victim@other.co.kr").one()
        assert consent_service.can_send_marketing(lead) is False
        assert all(not m["subject"].startswith(email_templates.AD_PREFIX) for m in captured_mail)

        # 확인 전에는 주기 발송 대상에도 잡히지 않는다
        assert _run_task(db_session)["leads_checked"] == 0

    def test_get_status_does_not_confirm(self, client, db_session, busan_new_notice, captured_mail):
        """GET 조회로는 확인되지 않는다 — 메일 스캐너 프리페치로 인한 오확인 방지."""
        from app.db import models

        resp = client.post("/api/v1/leads/capture", json=self._capture_body(email="prefetch@company.com"))
        lead = db_session.get(models.Lead, resp.json()["lead_id"])
        token = _optin_token(lead.id)

        status = client.get("/api/v1/optin/status", params={"token": token})
        assert status.status_code == 200
        assert status.json()["confirmed"] is False

        db_session.refresh(lead)
        assert consent_service.can_send_marketing(lead) is False

    def test_post_optin_confirms_and_sends_welcome(self, client, db_session, busan_new_notice, captured_mail):
        """확인 버튼(POST)을 눌러야 발송 대상이 되고, 그때 웰컴(광고)이 나간다."""
        from app.db import models

        resp = client.post("/api/v1/leads/capture", json=self._capture_body(email="ok@company.com"))
        lead = db_session.get(models.Lead, resp.json()["lead_id"])
        captured_mail.clear()   # 확인 메일은 검증했으므로 비우고 웰컴만 본다

        confirmed = client.post("/api/v1/optin", params={"token": _optin_token(lead.id)})
        assert confirmed.status_code == 200
        assert confirmed.json()["already"] is False

        db_session.refresh(lead)
        assert consent_service.can_send_marketing(lead) is True

        assert len(captured_mail) == 1
        assert captured_mail[0]["subject"].startswith(email_templates.AD_PREFIX)
        # 광고 메일에는 원클릭 수신거부 헤더가 반드시 붙는다(RFC 8058)
        assert "List-Unsubscribe" in captured_mail[0]["headers"]

    def test_optin_is_idempotent(self, client, db_session, busan_new_notice, captured_mail):
        """확인을 두 번 눌러도 웰컴은 한 통."""
        from app.db import models

        resp = client.post("/api/v1/leads/capture", json=self._capture_body(email="twice@company.com"))
        lead = db_session.get(models.Lead, resp.json()["lead_id"])
        token = _optin_token(lead.id)
        captured_mail.clear()

        client.post("/api/v1/optin", params={"token": token})
        second = client.post("/api/v1/optin", params={"token": token})
        assert second.json()["already"] is True
        assert len(captured_mail) == 1

    def test_withdrawn_lead_cannot_be_revived_by_optin(self, client, db_session, busan_new_notice, captured_mail):
        """철회한 사람이 옛 확인 링크를 눌러도 되살아나지 않는다."""
        from app.db import models

        resp = client.post("/api/v1/leads/capture", json=self._capture_body(email="gone@company.com"))
        lead = db_session.get(models.Lead, resp.json()["lead_id"])
        consent_service.withdraw_marketing(db_session, lead, subject_type="lead", source="test")
        db_session.commit()
        captured_mail.clear()

        result = client.post("/api/v1/optin", params={"token": _optin_token(lead.id)})
        assert result.status_code == 400

        db_session.refresh(lead)
        assert consent_service.can_send_marketing(lead) is False
        assert captured_mail == []

    def test_welcome_marks_capped_count(self, client, db_session, busan_new_notice, captured_mail):
        """매칭 상한에 걸린 건수는 "50건+" 으로 말한다 — 딱 떨어지게 말하면 거짓이 된다."""
        from app.db import models
        from app.services import lead_matching

        resp = client.post("/api/v1/leads/capture", json=self._capture_body(email="cap@company.com"))
        lead = db_session.get(models.Lead, resp.json()["lead_id"])
        lead.matched_count = lead_matching.MATCH_LIMIT      # 상한에 걸린 상태로 고정
        db_session.commit()
        captured_mail.clear()

        client.post("/api/v1/optin", params={"token": _optin_token(lead.id)})

        assert f"{lead_matching.MATCH_LIMIT}건+" in captured_mail[0]["subject"]
        assert f"{lead_matching.MATCH_LIMIT}건+" in captured_mail[0]["text"]

    def test_welcome_exact_count_has_no_plus(self, client, db_session, busan_new_notice, captured_mail):
        """상한 미만이면 정확한 수이므로 "+" 를 붙이지 않는다."""
        from app.db import models

        resp = client.post("/api/v1/leads/capture", json=self._capture_body(email="exact@company.com"))
        lead = db_session.get(models.Lead, resp.json()["lead_id"])
        lead.matched_count = 3
        db_session.commit()
        captured_mail.clear()

        client.post("/api/v1/optin", params={"token": _optin_token(lead.id)})

        assert "3건" in captured_mail[0]["subject"]
        assert "3건+" not in captured_mail[0]["subject"]

    def test_bad_token_rejected(self, client, db_session, busan_new_notice):
        """서명이 맞지 않는 토큰은 거부된다."""
        assert client.post("/api/v1/optin", params={"token": "forged.sig"}).status_code == 400
        assert client.get("/api/v1/optin/status", params={"token": "forged.sig"}).status_code == 400

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

    def test_control_chars_are_stripped_at_capture(self, client, db_session, busan_new_notice, captured_mail):
        """개행이 든 입력은 저장 전에 정제된다 — 그대로 두면 메일 제목 조립이 터진다."""
        from app.db import models

        resp = client.post(
            "/api/v1/leads/capture",
            json=self._capture_body(email="ctrl@company.com", region="부산광역시\n경상남도"),
        )
        assert resp.status_code == 200

        lead = db_session.get(models.Lead, resp.json()["lead_id"])
        assert "\n" not in (lead.region or "")
        assert lead.region == "부산광역시 경상남도"
        assert len(captured_mail) == 1      # 조립 실패 없이 확인 메일이 나갔다

    def test_same_person_recapturing_gets_one_welcome(self, client, db_session, busan_new_notice, captured_mail):
        """같은 사람이 재진단해 Lead 행이 늘어도 웰컴은 한 통 — 멱등 주체는 수신자."""
        body = self._capture_body(email="Repeat@Company.com")
        first = client.post("/api/v1/leads/capture", json=body)
        second = client.post("/api/v1/leads/capture", json=dict(body, email="repeat@company.com"))
        assert first.json()["lead_id"] != second.json()["lead_id"]   # 행은 둘
        captured_mail.clear()

        for lead_id in (first.json()["lead_id"], second.json()["lead_id"]):
            client.post("/api/v1/optin", params={"token": _optin_token(lead_id)})

        assert len(captured_mail) == 1      # 사람은 하나 → 웰컴도 하나


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

    def test_one_bad_lead_does_not_kill_the_batch(self, db_session, busan_new_notice):
        """리드 1건의 데이터 결함이 배치를 끊지 않는다 — 나머지는 정상 발송된다.

        정제가 들어간 지금도 과거 데이터·다른 경로로 개행이 든 값이 남아 있을 수 있다.
        그때 배치가 통째로 죽으면 매주 같은 지점에서 전원이 조용히 메일을 못 받는다.

        `captured_mail` 을 쓰지 않는 이유: mailer.send 를 통째로 가짜로 바꾸면 제목 조립
        (build_message)이 호출되지 않아 이 실패 경로가 재현되지 않는다. dry-run 경로는
        실제로 조립을 수행하므로 여기서는 그대로 태운다.
        """
        from app.db import models

        _consented_lead(db_session, email="poison@company.com", region="부산광역시\n경상남도")
        _consented_lead(db_session, email="healthy@company.com")

        result = _run_task(db_session)

        assert result["leads_checked"] == 2
        assert result["errors"] == 0                     # 예외가 아니라 failed 로 수렴
        assert result["sent"] == 1                       # 정상 리드는 받았다

        rows = {r.email: r for r in db_session.query(models.OutboundMessage).all()}
        assert rows["poison@company.com"].status == "failed"
        # 실패는 키를 놓아 재시도 여지를 남긴다(유령행 금지)
        assert rows["poison@company.com"].dedupe_key is None
        assert rows["healthy@company.com"].status == "dry_run"

    def test_same_person_multiple_rows_gets_one_mail(self, db_session, busan_new_notice, captured_mail):
        """같은 사람의 Lead 행이 여럿이어도 주간 메일은 한 통."""
        _consented_lead(db_session, email="dup@company.com")
        _consented_lead(db_session, email="DUP@Company.com")

        result = _run_task(db_session)

        assert result["sent"] == 1
        assert len(captured_mail) == 1

    def test_fresh_lead_does_not_get_duplicate_of_welcome(self, db_session, busan_new_notice, captured_mail):
        """갓 캡처된 리드에게는 웰컴이 이미 보여준 공고를 다시 보내지 않는다."""
        _consented_lead(db_session, email="fresh@company.com", created_at=_utcnow())

        result = _run_task(db_session)

        assert result["sent"] == 0
        assert result["skipped_no_match"] == 1
        assert captured_mail == []


class TestLeadMatchLinks:
    """매칭 메일의 링크 계약 (2026-08-04).

    실제 첫 발송에서 드러난 문제: 메일이 "24건"이라 말하면서 5건만 보여주고,
    「전체 목록 보기」는 **빈 진단 폼**으로 보냈다. 나머지를 보려면 업종·지역을
    다시 입력해야 했다 — 약속한 목록을 주지 못한 것이다.

    지키려는 사실:
      1) 공고마다 상세 페이지 링크가 있다(HTML·텍스트 양쪽 — HTML 차단 클라이언트에서
         링크 없는 목록으로 전락하지 않게).
      2) 목록 링크는 조건을 실어 보내 **클릭 한 번에** 결과가 뜬다.
      3) 모든 링크에 UTM 이 붙는다 — 없으면 이 메일의 유입이 direct 로 뭉개져
         효과를 측정할 수 없다.
      4) bid_no 가 없는 공고는 **깨진 링크 대신** 제목만 렌더한다.
    """

    CTX = {
        "region": "부산",
        "industry": "전기공사",
        "new_count": 24,
        "capped": False,
        "notices": [
            {"title": "가로등 정비공사", "organization": "부산시", "end_date_label": "08/12",
             "bid_no": "R26BK01661537-000"},
            {"title": "청사 전기설비 보수", "organization": "부산교육청", "end_date_label": "08/15",
             "bid_no": "R26BK01661538-000"},
        ],
    }

    def _render(self, ctx=None):
        return email_templates.render(
            "lead_new_matches", ctx or self.CTX, unsubscribe_url="https://bideasy.kr/unsubscribe?t=x"
        )

    def test_each_notice_links_to_its_detail_page(self):
        r = self._render()
        for no in ("R26BK01661537-000", "R26BK01661538-000"):
            assert f"/bid/{no}" in r.html, f"{no} 상세 링크가 HTML 에 없다"
            assert f"/bid/{no}" in r.text, f"{no} 상세 링크가 텍스트 판본에 없다"

    def test_list_cta_carries_conditions_and_autoruns(self):
        r = self._render()
        # 조건이 실려야 클릭 한 번에 24건이 뜬다. 한글은 URL 인코딩된 형태로 들어간다.
        assert "/diagnose?" in r.html
        assert "auto=1" in r.html
        from urllib.parse import quote
        assert quote("전기공사") in r.html
        assert quote("부산") in r.html

    def test_all_links_carry_utm(self):
        r = self._render()
        import re
        links = re.findall(r'https://[^"\s<)]+', r.html + " " + r.text)
        targets = [u for u in links if "/bid/" in u or "/diagnose" in u]
        assert targets, "검사할 링크가 없다"
        for u in targets:
            assert "utm_source=email" in u and "utm_campaign=lead_new_matches" in u, u

    def test_notice_without_bid_no_renders_without_link(self):
        ctx = dict(self.CTX)
        ctx["notices"] = [{"title": "공고번호 없는 건", "organization": "어딘가",
                           "end_date_label": "08/20", "bid_no": ""}]
        r = self._render(ctx)
        assert "공고번호 없는 건" in r.html
        assert "/bid/" not in r.html          # 깨진 링크를 만들지 않는다
        assert "/bid/" not in r.text

    def test_still_an_ad_with_legal_markers(self):
        """링크를 붙였다고 법정 표기가 사라지면 안 된다."""
        r = self._render()
        assert r.subject.startswith(email_templates.AD_PREFIX)
        assert "unsubscribe" in r.html
