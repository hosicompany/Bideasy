"""메시지 검증부터 실제 공고 활성화까지의 creative 귀속 회귀 테스트."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
from jose import jwt as jose_jwt

from app.api.v1.endpoints.message_validation import (
    CAMPAIGN_KEY,
    _lock_assignment_cohort,
    code_response,
    summarize_rows,
)
from app.core.config import settings
from app.core.security import (
    ALGORITHM,
    SECRET_KEY,
    InvalidNoticeCheckReceipt,
    create_access_token,
    create_notice_check_receipt,
    verify_notice_check_receipt,
)
from app.db import models


ACCESS_KEY = "permissioned-growth-test-key"
EXTENSION_ID = "a" * 32


@pytest.fixture(autouse=True)
def _isolate_growth_state(db_session, monkeypatch):
    """세션 DB에 커밋되는 퍼널 원장을 테스트마다 비우고 운영 설정을 복원한다."""
    import app.api.v1.endpoints.leads as leads_mod

    previous = {
        "message_enabled": settings.MESSAGE_TEST_ENABLED,
        "message_keys": settings.MESSAGE_TEST_ACCESS_KEYS,
        "message_image_path": settings.MESSAGE_TEST_IMAGE_PATH,
        "message_image_caption": settings.MESSAGE_TEST_IMAGE_CAPTION,
        "extension_id": settings.CHROME_EXTENSION_ID,
    }
    settings.MESSAGE_TEST_ENABLED = True
    settings.MESSAGE_TEST_ACCESS_KEYS = ACCESS_KEY
    settings.MESSAGE_TEST_IMAGE_PATH = "/guide-assets/test-electric-notice.png"
    settings.MESSAGE_TEST_IMAGE_CAPTION = (
        "공개 G2B 전기공사 화면 · 공고번호 R26BK00000000-000 · 2026-08-14 기준"
    )
    settings.CHROME_EXTENSION_ID = EXTENSION_ID
    monkeypatch.setattr(settings, "APP_ENV", "development")
    monkeypatch.setattr(leads_mod, "_get_redis", lambda: None)
    leads_mod._ip_call_log.clear()

    db_session.query(models.GrowthEvent).delete()
    db_session.query(models.MessageTestParticipant).delete()
    db_session.commit()
    yield
    db_session.rollback()
    db_session.query(models.GrowthEvent).delete()
    db_session.query(models.MessageTestParticipant).delete()
    db_session.commit()
    leads_mod._ip_call_log.clear()
    settings.MESSAGE_TEST_ENABLED = previous["message_enabled"]
    settings.MESSAGE_TEST_ACCESS_KEYS = previous["message_keys"]
    settings.MESSAGE_TEST_IMAGE_PATH = previous["message_image_path"]
    settings.MESSAGE_TEST_IMAGE_CAPTION = previous["message_image_caption"]
    settings.CHROME_EXTENSION_ID = previous["extension_id"]


def _creative(db, *, status="APPROVED", landing_path="/calculator", variant="A"):
    row = models.CreativeBrief(
        id=str(uuid4()),
        source_type="manual",
        campaign_key=f"test_growth_{uuid4().hex}",
        concept_key="mechanism",
        variant=variant,
        channel="test",
        format="static_1_1",
        hook="나라장터 공고 옆에서, 자격·A값·하한선을 한 번에.",
        body_copy="보고 있는 공고 화면에서 확인하세요.",
        cta_copy="이 공고 확인하기",
        landing_path=landing_path,
        utm_source="naver",
        utm_medium="organic",
        utm_campaign="message-validation",
        generation_spec_json={},
        status=status,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _screening_payload(**overrides):
    payload = {
        "access_key": ACCESS_KEY,
        "industry": "전기공사",
        "staff_count": 4,
        "directly_handles_bids": True,
        "monthly_notice_reviews": 20,
    }
    payload.update(overrides)
    return payload


def _response_payload(token: str, **overrides):
    payload = {
        "access_key": ACCESS_KEY,
        "participant_token": token,
        "exposure_ms": 5000,
        "service_understanding": "나라장터 공공입찰 공고를 확인하는 서비스",
        "usage_moment": "투찰 전 공고 옆에서 사용",
        "checked_items": "자격과 A값, 하한선을 한 화면에서 확인",
        "trust_score": 4,
        "relevance_score": 5,
    }
    payload.update(overrides)
    return payload


def _auth_headers(user: models.User, *, origin: str | None = None) -> dict[str, str]:
    token = create_access_token({"sub": str(user.id), "tv": user.token_version or 0})
    headers = {"Authorization": f"Bearer {token}"}
    if origin is not None:
        headers["Origin"] = origin
    return headers


def _context_receipt(client, user: models.User, bid_no: str, *, origin: str) -> str:
    response = client.get(
        f"/api/v1/bids/{bid_no}/context",
        headers=_auth_headers(user, origin=origin),
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["found"] is True
    assert payload["activation_receipt"]
    return str(payload["activation_receipt"])


def test_message_assignment_is_stable_and_balanced_within_cohort(client, db_session):
    assignments = []
    for _ in range(8):
        response = client.post("/api/v1/message-test/assign", json=_screening_payload())
        assert response.status_code == 200, response.text
        assignments.append(response.json())

    counts = {
        variant: sum(item["variant"] == variant for item in assignments)
        for variant in ("A", "B")
    }
    assert abs(counts["A"] - counts["B"]) <= 1

    first = assignments[0]
    repeated = client.post(
        "/api/v1/message-test/assign",
        json=_screening_payload(
            participant_token=first["participant_token"],
            monthly_notice_reviews=0,
        ),
    )
    assert repeated.status_code == 200
    assert repeated.json()["variant"] == first["variant"]
    assert repeated.json()["participant_token"] == first["participant_token"]

    rows = db_session.query(models.MessageTestParticipant).all()
    assert len(rows) == 8
    assert db_session.query(models.GrowthEvent).filter_by(event_name="qualified_visit").count() == 8

    ineligible = client.post(
        "/api/v1/message-test/assign",
        json=_screening_payload(industry="일반소매", staff_count=20),
    )
    assert ineligible.status_code == 200
    assert ineligible.json()["eligible"] is False
    assert db_session.query(models.MessageTestParticipant).count() == 8


def test_message_assignment_fails_closed_without_safe_approved_image(client):
    for path, caption in (
        ("", ""),
        ("https://evil.example/ad.png", "외부 화면"),
        ("/guide-assets/../private.png", "경로 이탈"),
        (
            "/guide-assets/%2e%2e/private.png",
            "공개 G2B 화면 · 공고번호 R26BK00000000-000 · 2026-08-14 기준",
        ),
        ("/guide-assets/safe.png", "공개 G2B 화면 · 기준일만 있음"),
    ):
        settings.MESSAGE_TEST_IMAGE_PATH = path
        settings.MESSAGE_TEST_IMAGE_CAPTION = caption
        response = client.post(
            "/api/v1/message-test/assign",
            json=_screening_payload(),
        )
        assert response.status_code == 503, response.text


def test_message_assignment_uses_postgres_transaction_lock_and_sqlite_noop():
    class FakeBind:
        def __init__(self, dialect_name):
            self.dialect = type("Dialect", (), {"name": dialect_name})()

    class FakeSession:
        def __init__(self, dialect_name):
            self.bind = FakeBind(dialect_name)
            self.calls = []

        def get_bind(self):
            return self.bind

        def execute(self, statement, params):
            self.calls.append((str(statement), params))

    postgres = FakeSession("postgresql")
    _lock_assignment_cohort(postgres, "same-cohort")
    _lock_assignment_cohort(postgres, "same-cohort")
    assert len(postgres.calls) == 2
    assert postgres.calls[0][0] == "SELECT pg_advisory_xact_lock(:lock_key)"
    assert postgres.calls[0][1]["lock_key"] == postgres.calls[1][1]["lock_key"]
    assert -(2**63) <= postgres.calls[0][1]["lock_key"] < 2**63

    sqlite = FakeSession("sqlite")
    _lock_assignment_cohort(sqlite, "same-cohort")
    assert sqlite.calls == []


def test_message_response_enforces_exposure_and_records_predefined_coding(client, db_session):
    assigned = client.post("/api/v1/message-test/assign", json=_screening_payload()).json()
    token = assigned["participant_token"]

    forged_elapsed = client.post(
        "/api/v1/message-test/responses",
        json=_response_payload(token, exposure_ms=5000),
    )
    assert forged_elapsed.status_code == 400

    row = db_session.query(models.MessageTestParticipant).filter_by(participant_token=token).one()
    row.assigned_at = datetime.now(timezone.utc) - timedelta(seconds=6)
    db_session.add(row)
    db_session.commit()

    too_fast = client.post(
        "/api/v1/message-test/responses",
        json=_response_payload(token, exposure_ms=4499),
    )
    assert too_fast.status_code == 400

    accepted = client.post(
        "/api/v1/message-test/responses",
        json=_response_payload(token),
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json() == {"accepted": True, "already_submitted": False}

    db_session.refresh(row)
    assert row.codes_hit == 4
    assert row.prediction_misunderstood is False
    assert row.coding_json["version"] == "ko-v1"
    assert all(row.coding_json["codes"].values())

    duplicate = client.post(
        "/api/v1/message-test/responses",
        json=_response_payload(token, trust_score=1),
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["already_submitted"] is True
    db_session.refresh(row)
    assert row.trust_score == 4


def test_message_coding_and_preregistered_pass_gate():
    misunderstood = code_response(
        "나라장터 낙찰가를 예측해 주는 서비스",
        "투찰 전",
        "자격과 A값을 한 화면에서 확인",
    )
    assert misunderstood["codes_hit"] == 4
    assert misunderstood["prediction_misunderstood"] is True

    now = datetime.now(timezone.utc)
    rows = [
        models.MessageTestParticipant(
            participant_token=f"participant-token-{index:04d}",
            campaign_key=CAMPAIGN_KEY,
            cohort_key="cohort",
            variant="A",
            industry="전기공사",
            staff_count=3,
            directly_handles_bids=True,
            monthly_notice_reviews=20,
            submitted_at=now,
            trust_score=4,
            codes_hit=3 if index < 7 else 2,
            prediction_misunderstood=index == 0,
        )
        for index in range(10)
    ]
    summary = summarize_rows(rows)
    assert summary == {
        "assigned": 10,
        "submitted": 10,
        "understood_3_of_4": 7,
        "trust_median": 4.0,
        "prediction_misunderstood": 1,
        "enough_sample": True,
        "passed_gate": True,
    }

    rows[1].prediction_misunderstood = True
    assert summarize_rows(rows)["passed_gate"] is False
    assert summarize_rows(rows[:9])["enough_sample"] is False

    # 표본이 10명을 넘더라도 고정 7명이 아니라 70% 이해 기준을 유지한다.
    rows[1].prediction_misunderstood = False
    rows.append(
        models.MessageTestParticipant(
            participant_token="participant-token-extra",
            campaign_key=CAMPAIGN_KEY,
            cohort_key="cohort",
            variant="A",
            industry="전기공사",
            staff_count=3,
            directly_handles_bids=True,
            monthly_notice_reviews=20,
            submitted_at=now,
            trust_score=4,
            codes_hit=2,
            prediction_misunderstood=False,
        )
    )
    assert summarize_rows(rows)["passed_gate"] is False
    rows[-1].codes_hit = 3
    assert summarize_rows(rows)["passed_gate"] is True


def test_creative_redirect_allows_only_approved_internal_landing_and_dedupes(client, db_session):
    creative = _creative(db_session, landing_path="/calculator?existing=1", variant="B")
    anonymous_id = "fixed-anonymous-token-1234567890"
    headers = {"Cookie": f"bd_go_anon={anonymous_id}", "Referer": "https://allowed.example/post"}

    first = client.get(f"/go/{creative.id}", headers=headers, follow_redirects=False)
    assert first.status_code == 302, first.text
    location = urlsplit(first.headers["location"])
    assert location.path == "/calculator"
    query = parse_qs(location.query)
    assert query == {
        "existing": ["1"],
        "utm_source": ["naver"],
        "utm_medium": ["organic"],
        "utm_campaign": ["message-validation"],
        "utm_content": ["B"],
        "creative_id": [creative.id],
    }
    set_cookie = first.headers["set-cookie"]
    assert "bd_go_anon=" in set_cookie
    assert "bd_anon=" in set_cookie
    assert "Secure" in set_cookie
    assert "HttpOnly" in set_cookie

    second = client.get(f"/go/{creative.id}", headers=headers, follow_redirects=False)
    assert second.status_code == 302
    events = db_session.query(models.GrowthEvent).filter_by(creative_id=creative.id).all()
    assert len(events) == 1
    assert events[0].anonymous_id == anonymous_id
    assert events[0].utm_content == "B"

    draft = _creative(db_session, status="DRAFT")
    assert client.get(f"/go/{draft.id}", follow_redirects=False).status_code == 404

    external = _creative(db_session, landing_path="https://evil.example/phish")
    blocked = client.get(f"/go/{external.id}", follow_redirects=False)
    assert blocked.status_code == 400
    assert "location" not in blocked.headers

    conflicting = _creative(
        db_session,
        landing_path=(
            "/calculator?existing=kept&creative_id=stale-id"
            "&utm_source=stale&utm_content=stale"
        ),
    )
    canonical = client.get(f"/go/{conflicting.id}", follow_redirects=False)
    canonical_query = parse_qs(urlsplit(canonical.headers["location"]).query)
    assert canonical_query["existing"] == ["kept"]
    assert canonical_query["creative_id"] == [conflicting.id]
    assert canonical_query["utm_source"] == ["naver"]
    assert canonical_query["utm_content"] == ["A"]

    fragment = _creative(db_session, landing_path="/calculator#https://evil.example")
    assert client.get(f"/go/{fragment.id}", follow_redirects=False).status_code == 400
    encoded_traversal = _creative(
        db_session,
        landing_path="/blog/%2e%2e/calculator",
    )
    assert (
        client.get(f"/go/{encoded_traversal.id}", follow_redirects=False).status_code
        == 400
    )
    encoded_control = _creative(
        db_session,
        landing_path="/blog/safe%0d%0aX-Injected:yes",
    )
    assert (
        client.get(f"/go/{encoded_control.id}", follow_redirects=False).status_code
        == 400
    )


def test_public_growth_event_requires_publishable_creative_and_dedupes(client, db_session):
    approved = _creative(db_session)
    draft = _creative(db_session, status="DRAFT")
    payload = {
        "event_name": "free_value_completed",
        "event_id": "growth-event-00000001",
        "anonymous_id": "anonymous-user-00000001",
        "creative_id": approved.id,
        "utm_source": "naver",
        "utm_content": "message_a",
        "metadata": {"surface": "calculator"},
    }

    first = client.post("/api/v1/growth/events", json=payload)
    assert first.status_code == 202, first.text
    assert first.json()["duplicate"] is False
    duplicate = client.post("/api/v1/growth/events", json=payload)
    assert duplicate.status_code == 202
    assert duplicate.json()["duplicate"] is True

    event = db_session.query(models.GrowthEvent).filter_by(dedupe_key="web:growth-event-00000001").one()
    assert event.creative_id == approved.id
    assert event.utm_content == "message_a"
    assert event.event_metadata_json == {"surface": "calculator"}

    rejected = client.post(
        "/api/v1/growth/events",
        json={**payload, "event_id": "growth-event-00000002", "creative_id": draft.id},
    )
    assert rejected.status_code == 400
    invalid_name = client.post(
        "/api/v1/growth/events",
        json={**payload, "event_id": "growth-event-00000003", "event_name": "qualified_visit"},
    )
    assert invalid_name.status_code == 400
    assert db_session.query(models.GrowthEvent).count() == 1


def test_extension_notice_check_requires_origin_auth_real_notice_and_preserves_first_touch(
    client,
    db_session,
):
    signup_creative = _creative(db_session)
    attempted_override = _creative(db_session, variant="B")
    user = models.User(
        email=f"growth-extension-{uuid4().hex}@test.com",
        hashed_password="x",
        tier="free",
        signup_source="naver",
        signup_medium="organic",
        signup_campaign="message-validation",
        signup_content="message_a",
        signup_creative_id=signup_creative.id,
    )
    bid_no = f"GROWTH-{uuid4().hex[:12]}"
    db_session.add(user)
    db_session.add(models.Notice(bid_no=bid_no, title="실제 저장 공고"))
    db_session.commit()
    db_session.refresh(user)
    # 가입 당시에는 승인된 소재였지만 이후 정본 변경으로 STALE이 된 과거 유입도
    # 실제 활성화 귀속에서 사라지면 안 된다.
    signup_creative.status = "STALE"
    db_session.add(signup_creative)
    db_session.commit()
    correct_origin = f"chrome-extension://{EXTENSION_ID}"

    no_auth = client.post(
        "/api/v1/growth/extension/notice-check",
        headers={"Origin": correct_origin},
        json={"bid_no": bid_no, "receipt": "x" * 80},
    )
    assert no_auth.status_code == 401

    wrong_origin = client.post(
        "/api/v1/growth/extension/notice-check",
        headers=_auth_headers(user, origin="chrome-extension://" + "b" * 32),
        json={"bid_no": bid_no, "receipt": "x" * 80},
    )
    assert wrong_origin.status_code == 403

    unknown = client.post(
        "/api/v1/growth/extension/notice-check",
        headers=_auth_headers(user, origin=correct_origin),
        json={"bid_no": "NOT-A-REAL-BID", "receipt": "x" * 80},
    )
    assert unknown.status_code == 400

    # 활성화 전에 받은 서로 다른 두 context receipt는 각각 1회만 쓸 수 있다.
    accepted_receipt = _context_receipt(client, user, bid_no, origin=correct_origin)
    duplicate_receipt = _context_receipt(client, user, bid_no, origin=correct_origin)

    accepted = client.post(
        "/api/v1/growth/extension/notice-check",
        headers=_auth_headers(user, origin=correct_origin),
        json={
            "bid_no": f"  {bid_no}  ",
            "receipt": accepted_receipt,
            "creative_id": attempted_override.id,
        },
    )
    assert accepted.status_code == 202, accepted.text
    assert accepted.json()["duplicate"] is False

    event = db_session.query(models.GrowthEvent).filter_by(event_name="notice_check_completed").one()
    assert event.bid_no == bid_no
    assert event.creative_id == signup_creative.id
    assert event.utm_content == "message_a"
    db_session.refresh(user)
    assert user.first_activation_at is not None

    # 이미 이벤트가 있는 legacy/race 상태에서 활성화 시각만 비었어도 복구한다.
    user.first_activation_at = None
    db_session.add(user)
    db_session.commit()
    duplicate = client.post(
        "/api/v1/growth/extension/notice-check",
        headers=_auth_headers(user, origin=correct_origin),
        json={"bid_no": bid_no, "receipt": duplicate_receipt},
    )
    assert duplicate.status_code == 202
    assert duplicate.json()["duplicate"] is True
    assert db_session.query(models.GrowthEvent).filter_by(event_name="notice_check_completed").count() == 1
    db_session.refresh(user)
    assert user.first_activation_at is not None


def test_extension_notice_check_resolves_base_notice_number_and_rejects_bad_shape(
    client,
    db_session,
):
    user = models.User(
        email=f"growth-base-notice-{uuid4().hex}@test.com",
        hashed_password="x",
        tier="free",
    )
    base_bid_no = f"R26BK{uuid4().hex[:10].upper()}"
    canonical_bid_no = f"{base_bid_no}-000"
    db_session.add(user)
    db_session.add(models.Notice(bid_no=canonical_bid_no, title="차수가 있는 실제 공고"))
    db_session.commit()
    db_session.refresh(user)
    headers = _auth_headers(
        user,
        origin=f"chrome-extension://{EXTENSION_ID}",
    )
    receipt = _context_receipt(
        client,
        user,
        base_bid_no,
        origin=f"chrome-extension://{EXTENSION_ID}",
    )

    accepted = client.post(
        "/api/v1/growth/extension/notice-check",
        headers=headers,
        json={"bid_no": base_bid_no, "receipt": receipt},
    )
    assert accepted.status_code == 202, accepted.text
    event = db_session.query(models.GrowthEvent).filter_by(
        event_name="notice_check_completed",
        user_id=user.id,
    ).one()
    assert event.bid_no == canonical_bid_no
    assert event.dedupe_key == f"notice-check:{user.id}:{canonical_bid_no}"

    malformed = client.post(
        "/api/v1/growth/extension/notice-check",
        headers=headers,
        json={"bid_no": "../../etc/passwd", "receipt": "x" * 80},
    )
    assert malformed.status_code == 422


def test_notice_check_receipt_is_minimal_bound_and_expires():
    bid_no = "R26BK01543466-000"
    receipt = create_notice_check_receipt(user_id=17, bid_no=bid_no)
    claims = jose_jwt.decode(receipt, SECRET_KEY, algorithms=[ALGORITHM])

    assert set(claims) == {"purpose", "user_id", "bid_no", "nonce", "iat", "exp"}
    assert claims["user_id"] == 17
    assert claims["bid_no"] == bid_no
    assert not ({"email", "url", "referrer", "creative_id"} & set(claims))
    assert (
        verify_notice_check_receipt(
            receipt,
            expected_user_id=17,
            expected_bid_no=bid_no,
        )
        == claims["nonce"]
    )

    with pytest.raises(InvalidNoticeCheckReceipt):
        verify_notice_check_receipt(
            receipt,
            expected_user_id=18,
            expected_bid_no=bid_no,
        )
    with pytest.raises(InvalidNoticeCheckReceipt):
        verify_notice_check_receipt(
            receipt,
            expected_user_id=17,
            expected_bid_no="R26BK01543467-000",
        )

    now = datetime.now(timezone.utc)
    expired = jose_jwt.encode(
        {
            "purpose": "notice_check_activation",
            "user_id": 17,
            "bid_no": bid_no,
            "nonce": "a" * 24,
            "iat": now - timedelta(seconds=10),
            "exp": now - timedelta(seconds=1),
        },
        SECRET_KEY,
        algorithm=ALGORITHM,
    )
    with pytest.raises(InvalidNoticeCheckReceipt):
        verify_notice_check_receipt(
            expired,
            expected_user_id=17,
            expected_bid_no=bid_no,
        )


def test_context_receipt_closes_direct_post_and_is_one_time(
    client,
    db_session,
):
    attempted_override = _creative(db_session)
    user = models.User(
        email=f"growth-receipt-{uuid4().hex}@test.com",
        hashed_password="x",
        tier="free",
    )
    other_user = models.User(
        email=f"growth-receipt-other-{uuid4().hex}@test.com",
        hashed_password="x",
        tier="free",
    )
    bid_no = f"RECEIPT-{uuid4().hex[:12]}"
    other_bid_no = f"RECEIPT-{uuid4().hex[:12]}"
    db_session.add_all(
        (
            user,
            other_user,
            models.Notice(bid_no=bid_no, title="receipt 대상 실제 공고"),
            models.Notice(bid_no=other_bid_no, title="다른 실제 공고"),
        )
    )
    db_session.commit()
    db_session.refresh(user)
    db_session.refresh(other_user)
    origin = f"chrome-extension://{EXTENSION_ID}"

    anonymous_context = client.get(
        f"/api/v1/bids/{bid_no}/context",
        headers={"Origin": origin},
    )
    assert anonymous_context.status_code == 200
    assert anonymous_context.json()["activation_receipt"] is None

    wrong_origin_context = client.get(
        f"/api/v1/bids/{bid_no}/context",
        headers=_auth_headers(user, origin="chrome-extension://" + "b" * 32),
    )
    assert wrong_origin_context.status_code == 200
    assert wrong_origin_context.json()["activation_receipt"] is None

    # 이전 취약 경로: JWT + 위조 가능한 Origin만으로 직접 활성화하던 요청은
    # 실제 context 응답 receipt가 없으므로 이제 request contract에서 닫힌다.
    direct_post = client.post(
        "/api/v1/growth/extension/notice-check",
        headers=_auth_headers(user, origin=origin),
        json={"bid_no": bid_no},
    )
    assert direct_post.status_code == 422

    context = client.get(
        f"/api/v1/bids/{bid_no}/context",
        headers=_auth_headers(user, origin=origin),
    )
    assert context.status_code == 200, context.text
    assert context.headers["cache-control"] == "no-store"
    receipt = context.json()["activation_receipt"]
    assert isinstance(receipt, str) and receipt

    wrong_user = client.post(
        "/api/v1/growth/extension/notice-check",
        headers=_auth_headers(other_user, origin=origin),
        json={"bid_no": bid_no, "receipt": receipt},
    )
    assert wrong_user.status_code == 403
    wrong_bid = client.post(
        "/api/v1/growth/extension/notice-check",
        headers=_auth_headers(user, origin=origin),
        json={"bid_no": other_bid_no, "receipt": receipt},
    )
    assert wrong_bid.status_code == 403
    tampered = client.post(
        "/api/v1/growth/extension/notice-check",
        headers=_auth_headers(user, origin=origin),
        json={"bid_no": bid_no, "receipt": receipt + "x"},
    )
    assert tampered.status_code == 403

    accepted = client.post(
        "/api/v1/growth/extension/notice-check",
        headers=_auth_headers(user, origin=origin),
        json={"bid_no": bid_no, "receipt": receipt, "creative_id": attempted_override.id},
    )
    assert accepted.status_code == 202, accepted.text
    assert accepted.json() == {"accepted": True, "duplicate": False}

    replay = client.post(
        "/api/v1/growth/extension/notice-check",
        headers=_auth_headers(user, origin=origin),
        json={"bid_no": bid_no, "receipt": receipt},
    )
    assert replay.status_code == 409
    assert db_session.query(models.GrowthEvent).filter_by(
        event_name="notice_check_completed",
        user_id=user.id,
        bid_no=bid_no,
    ).count() == 1
    event = db_session.query(models.GrowthEvent).filter_by(
        event_name="notice_check_completed",
        user_id=user.id,
        bid_no=bid_no,
    ).one()
    assert event.creative_id is None

    consumed = db_session.query(models.GrowthEvent).filter_by(
        event_name="notice_check_receipt_consumed",
        user_id=user.id,
        bid_no=bid_no,
    ).one()
    nonce = jose_jwt.decode(receipt, SECRET_KEY, algorithms=[ALGORITHM])["nonce"]
    assert consumed.dedupe_key.startswith("notice-receipt:")
    assert nonce not in consumed.dedupe_key
    assert consumed.event_metadata_json == {"purpose": "notice_check_activation"}

    after_activation = client.get(
        f"/api/v1/bids/{bid_no}/context",
        headers=_auth_headers(user, origin=origin),
    )
    assert after_activation.status_code == 200
    assert after_activation.json()["activation_receipt"] is None


def test_context_rejects_like_wildcards_before_receipt_issuance(
    client,
    db_session,
):
    user = models.User(
        email=f"growth-wildcard-{uuid4().hex}@test.com",
        hashed_password="not-used",
        token_version=0,
    )
    db_session.add_all(
        [
            user,
            models.Notice(
                bid_no="R26BK01549999-000",
                title="와일드카드로 선택되면 안 되는 실제 공고",
            ),
        ]
    )
    db_session.commit()
    origin = f"chrome-extension://{EXTENSION_ID}"

    response = client.get(
        "/api/v1/bids/%25/context",
        headers=_auth_headers(user, origin=origin),
    )

    assert response.status_code == 400
    assert "공고번호 형식" in response.json()["detail"]
    assert (
        db_session.query(models.GrowthEvent)
        .filter(models.GrowthEvent.event_name == "notice_check_completed")
        .count()
        == 0
    )


def test_context_rejects_stale_bearer_instead_of_silently_downgrading(
    client,
    db_session,
):
    user = models.User(
        email=f"growth-stale-token-{uuid4().hex}@test.com",
        hashed_password="not-used",
        token_version=0,
    )
    bid_no = "R26BK01549998-000"
    db_session.add_all([user, models.Notice(bid_no=bid_no, title="stale token 대상")])
    db_session.commit()
    token = create_access_token(
        {"sub": str(user.id), "tv": user.token_version or 0},
        expires_delta=timedelta(seconds=-1),
    )

    response = client.get(
        f"/api/v1/bids/{bid_no}/context",
        headers={
            "Authorization": f"Bearer {token}",
            "Origin": f"chrome-extension://{EXTENSION_ID}",
        },
    )

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_context_rejects_provider_result_for_a_different_notice_order(
    client,
    db_session,
    monkeypatch,
):
    from app.services.bid_detail import BidDetailService

    user = models.User(
        email=f"growth-order-mismatch-{uuid4().hex}@test.com",
        hashed_password="not-used",
        token_version=0,
    )
    db_session.add(user)
    db_session.commit()
    requested = "R26BK01549997-001"
    returned = "R26BK01549997-000"
    monkeypatch.setattr(
        BidDetailService,
        "fetch_bid_detail_robust",
        staticmethod(
            lambda *_args, **_kwargs: {
                "bid_no": returned,
                "title": "다른 차수 공고",
                "raw_data": {},
            }
        ),
    )

    response = client.get(
        f"/api/v1/bids/{requested}/context",
        headers=_auth_headers(user, origin=f"chrome-extension://{EXTENSION_ID}"),
    )

    assert response.status_code == 200
    assert response.json()["found"] is False
    assert response.json()["bid_ntce_no"] == requested
    assert response.json()["activation_receipt"] is None
    assert db_session.query(models.Notice).filter(models.Notice.bid_no == returned).first() is None


def test_signup_and_lead_capture_preserve_content_and_only_approved_creative(
    client,
    db_session,
    monkeypatch,
):
    import app.api.v1.endpoints.auth as auth_mod

    monkeypatch.setattr(auth_mod, "_send_trial_welcome", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(auth_mod, "link_leads_to_user", lambda *_args, **_kwargs: None)
    approved = _creative(db_session)
    draft = _creative(db_session, status="DRAFT")

    approved_email = f"growth-signup-{uuid4().hex}@test.com"
    registered = client.post(
        "/api/v1/auth/register",
        json={
            "email": approved_email,
            "password": "Passw0rd!",
            "signup_source": "naver",
            "signup_medium": "organic",
            "signup_campaign": "message-validation",
            "signup_content": "message_a",
            "signup_creative_id": approved.id,
        },
    )
    assert registered.status_code == 200, registered.text
    registered_user = db_session.query(models.User).filter_by(email=approved_email).one()
    assert registered_user.signup_content == "message_a"
    assert registered_user.signup_creative_id == approved.id

    draft_email = f"growth-signup-{uuid4().hex}@test.com"
    registered_draft = client.post(
        "/api/v1/auth/register",
        json={
            "email": draft_email,
            "password": "Passw0rd!",
            "signup_content": "message_b",
            "signup_creative_id": draft.id,
        },
    )
    assert registered_draft.status_code == 200
    draft_user = db_session.query(models.User).filter_by(email=draft_email).one()
    assert draft_user.signup_content == "message_b"
    assert draft_user.signup_creative_id is None

    notice_id = f"LEAD-GROWTH-{uuid4().hex[:10]}"
    db_session.add(
        models.Notice(
            bid_no=notice_id,
            title="부산 테스트 전기공사",
            region="부산광역시",
            end_date=datetime.now() + timedelta(days=3),
        )
    )
    db_session.commit()

    lead_email = f"growth-lead-{uuid4().hex}@test.com"
    captured = client.post(
        "/api/v1/leads/capture",
        json={
            "email": lead_email,
            "industry": "전기공사",
            "region": "부산광역시",
            "utm_content": "message_a",
            "creative_id": approved.id,
        },
    )
    assert captured.status_code == 200, captured.text
    lead = db_session.query(models.Lead).filter_by(email=lead_email).one()
    assert lead.utm_content == "message_a"
    assert lead.creative_id == approved.id

    draft_lead_email = f"growth-lead-{uuid4().hex}@test.com"
    captured_draft = client.post(
        "/api/v1/leads/capture",
        json={
            "email": draft_lead_email,
            "industry": "전기공사",
            "region": "부산광역시",
            "utm_content": "message_b",
            "creative_id": draft.id,
        },
    )
    assert captured_draft.status_code == 200
    draft_lead = db_session.query(models.Lead).filter_by(email=draft_lead_email).one()
    assert draft_lead.utm_content == "message_b"
    assert draft_lead.creative_id is None


def test_admin_growth_funnel_counts_unique_activation_repeat_and_review_eligibility(
    admin_client,
    db_session,
):
    creative = _creative(db_session)
    user = models.User(
        email=f"growth-funnel-{uuid4().hex}@test.com",
        hashed_password="x",
        tier="free",
    )
    late_returning_user = models.User(
        email=f"growth-funnel-late-{uuid4().hex}@test.com",
        hashed_password="x",
        tier="free",
    )
    db_session.add_all((user, late_returning_user))
    db_session.flush()
    now = datetime.now(timezone.utc)
    events = [
        models.GrowthEvent(
            event_name="qualified_visit",
            dedupe_key="funnel-qualified-1",
            anonymous_id="funnel-anonymous-user",
            creative_id=creative.id,
            occurred_at=now - timedelta(days=11),
        ),
        models.GrowthEvent(
            event_name="qualified_visit",
            dedupe_key="funnel-qualified-2",
            anonymous_id="funnel-anonymous-user",
            creative_id=creative.id,
            occurred_at=now - timedelta(days=10),
        ),
    ]
    for index, (bid_no, days_ago) in enumerate((("BID-A", 9), ("BID-B", 8), ("BID-C", 8))):
        events.append(
            models.GrowthEvent(
                event_name="notice_check_completed",
                dedupe_key=f"funnel-notice-{index}",
                user_id=user.id,
                creative_id=creative.id,
                bid_no=bid_no,
                occurred_at=now - timedelta(days=days_ago),
            )
        )
    # 조회 구간의 최근 두 행만 보면 반복처럼 보이지만 실제 첫 확인은 100일 전이다.
    # 최초 28일 안에는 두 번째 공고가 없으므로 repeat_users_28d에 들어가면 안 된다.
    for index, (bid_no, days_ago) in enumerate((("OLD-FIRST", 100), ("LATE-A", 10), ("LATE-B", 5))):
        events.append(
            models.GrowthEvent(
                event_name="notice_check_completed",
                dedupe_key=f"funnel-late-notice-{index}",
                user_id=late_returning_user.id,
                bid_no=bid_no,
                occurred_at=now - timedelta(days=days_ago),
            )
        )
    db_session.add_all(events)
    db_session.commit()

    response = admin_client.get("/api/v1/admin/growth/creative-funnel?days=90")
    assert response.status_code == 200, response.text
    data = response.json()
    item = next(row for row in data["items"] if row["creative_id"] == creative.id)
    assert item["unique"]["qualified_visit"] == 1
    assert item["raw"]["qualified_visit"] == 2
    assert item["unique"]["notice_check_completed"] == 1
    assert item["raw"]["notice_check_completed"] == 3
    assert item["activation_rate_pct"] == 100.0
    assert data["overall"]["active_users"] == 2
    assert data["overall"]["repeat_users_28d"] == 1
    assert data["overall"]["review_eligible_users"] == 2


def test_extension_notice_check_uses_same_order_as_receipt_when_multiple_orders_exist(
    client,
    db_session,
):
    """재공고로 차수가 여럿인 공고에서 receipt 발급 공고와 활성화 검증 공고가 같아야 한다.

    회귀: growth 쪽 정본화가 오름차순(-000), bids 쪽 receipt 가 내림차순(-001)을
    골라 활성화 POST 가 영구 403 이던 결함. 차수를 두 개 심어야만 드러난다.
    """
    user = models.User(
        email=f"growth-multi-order-{uuid4().hex}@test.com",
        hashed_password="x",
        tier="free",
    )
    base_bid_no = f"R26BK{uuid4().hex[:10].upper()}"
    db_session.add(user)
    db_session.add_all([
        models.Notice(bid_no=f"{base_bid_no}-000", title="최초 공고"),
        models.Notice(bid_no=f"{base_bid_no}-001", title="재공고(최신 차수)"),
    ])
    db_session.commit()
    db_session.refresh(user)
    origin = f"chrome-extension://{EXTENSION_ID}"
    receipt = _context_receipt(client, user, base_bid_no, origin=origin)

    accepted = client.post(
        "/api/v1/growth/extension/notice-check",
        headers=_auth_headers(user, origin=origin),
        json={"bid_no": base_bid_no, "receipt": receipt},
    )
    assert accepted.status_code == 202, accepted.text
    event = db_session.query(models.GrowthEvent).filter_by(
        event_name="notice_check_completed",
        user_id=user.id,
    ).one()
    # 정본 규칙: 차수 없는 입력은 최신 차수로 결정적으로 보완한다 (bids.py 와 동일)
    assert event.bid_no == f"{base_bid_no}-001"
