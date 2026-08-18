"""허가형 메시지 검증 — 가동 전 실동작 검사.

구현 349줄에 테스트가 0건이었다(2026-08-18). 문서
`docs/CUSTOMER_VALIDATION_OPERATIONS.md` 가 약속한 안전장치들이 실제로 거는지
확인한다. 이 테스트가 없으면 "켜도 된다"는 판단의 근거가 문서뿐이다.
"""

import pytest

from app.core.config import settings
from app.db import models

KEY = "test-access-key-0123456789abcdef"
GOOD_IMAGE = "/guide-assets/01-main-g2b-with-sidepanel.png"
GOOD_CAPTION = "공개 G2B 화면 · 공고번호 R26BK00000000-000 · 2026-08-18 기준"

ELIGIBLE = {
    "access_key": KEY, "industry": "전기공사", "staff_count": 5,
    "directly_handles_bids": True, "monthly_notice_reviews": 20,
}


@pytest.fixture
def live(monkeypatch):
    """운영에서 켤 때와 같은 4값을 넣은 상태."""
    monkeypatch.setattr(settings, "MESSAGE_TEST_ENABLED", True)
    monkeypatch.setattr(settings, "MESSAGE_TEST_ACCESS_KEYS", KEY)
    monkeypatch.setattr(settings, "MESSAGE_TEST_IMAGE_PATH", GOOD_IMAGE)
    monkeypatch.setattr(settings, "MESSAGE_TEST_IMAGE_CAPTION", GOOD_CAPTION)


class TestGate:
    """켜지 않았거나 준비가 덜 되면 아무도 못 들어온다."""

    def test_disabled_returns_404(self, client, monkeypatch):
        monkeypatch.setattr(settings, "MESSAGE_TEST_ENABLED", False)
        assert client.post("/api/v1/message-test/assign", json=ELIGIBLE).status_code == 404

    def test_wrong_key_returns_403(self, client, live):
        body = {**ELIGIBLE, "access_key": "wrong-key-wrong-key-wrong-key"}
        assert client.post("/api/v1/message-test/assign", json=body).status_code == 403

    @pytest.mark.parametrize("path,caption", [
        ("", GOOD_CAPTION),                                   # 경로 없음
        (GOOD_IMAGE, ""),                                     # 캡션 없음
        ("/etc/passwd", GOOD_CAPTION),                        # 허용 prefix 밖
        ("/guide-assets/../../etc/passwd", GOOD_CAPTION),     # traversal
        (GOOD_IMAGE, "공고번호만 있고 출처가 없다 2026-08-18 기준"),  # 출처 누락
        (GOOD_IMAGE, "공개 G2B 화면 · 2026-08-18 기준"),       # 공고번호 누락
    ])
    def test_unapproved_image_blocks_with_503(self, client, live, monkeypatch, path, caption):
        """문서 약속: 네 값을 모두 검수하기 전에는 배정이 503 으로 막힌다.

        출처·공고번호·기준일이 빠진 캡션은 '어디서 온 화면인지 증명하지 못하는'
        스크린샷이라 참가자에게 보여줄 수 없다.
        """
        monkeypatch.setattr(settings, "MESSAGE_TEST_IMAGE_PATH", path)
        monkeypatch.setattr(settings, "MESSAGE_TEST_IMAGE_CAPTION", caption)
        assert client.post("/api/v1/message-test/assign", json=ELIGIBLE).status_code == 503


class TestScreening:
    """비치헤드 밖 참가자에게는 메시지를 보여주지 않는다."""

    @pytest.mark.parametrize("field,value", [
        ("industry", "소프트웨어"),          # 업종 밖
        ("staff_count", 50),                 # 1~10명 밖
        ("directly_handles_bids", False),    # 직접 투찰 아님
        ("monthly_notice_reviews", 3),       # 월 10건 미만
    ])
    def test_ineligible_gets_no_message(self, client, live, field, value):
        r = client.post("/api/v1/message-test/assign", json={**ELIGIBLE, field: value})
        assert r.status_code == 200
        body = r.json()
        assert body["eligible"] is False
        assert "copy" not in body and "variant" not in body, "부적격자에게 메시지가 샜다"

    def test_eligible_gets_assignment(self, client, live):
        body = client.post("/api/v1/message-test/assign", json=ELIGIBLE).json()
        assert body["eligible"] is True
        assert body["variant"] in ("A", "B")
        assert body["copy"]["headline"] and body["display_ms"] == 5000
        assert body["image_caption"] == GOOD_CAPTION


class TestAssignment:
    def test_same_token_stays_on_same_variant(self, client, live):
        """한 참가자는 한 메시지에 고정된다 — 다른 안을 보여주지 않는다."""
        first = client.post("/api/v1/message-test/assign", json=ELIGIBLE).json()
        token = first["participant_token"]
        for _ in range(3):
            again = client.post(
                "/api/v1/message-test/assign", json={**ELIGIBLE, "participant_token": token}
            ).json()
            assert again["variant"] == first["variant"]
            assert again["participant_token"] == token

    def test_balanced_within_cohort(self, client, live):
        """같은 코호트 안에서 A/B 수를 맞춘다(10명이면 5:5)."""
        seen = [
            client.post("/api/v1/message-test/assign", json=ELIGIBLE).json()["variant"]
            for _ in range(10)
        ]
        assert seen.count("A") == 5 and seen.count("B") == 5

    def test_token_from_another_cohort_is_rejected(self, client, live, monkeypatch):
        """다른 링크(코호트)에서 받은 토큰은 통하지 않는다."""
        token = client.post("/api/v1/message-test/assign", json=ELIGIBLE).json()["participant_token"]
        other = "other-cohort-key-0123456789abcdef"
        monkeypatch.setattr(settings, "MESSAGE_TEST_ACCESS_KEYS", f"{KEY},{other}")
        r = client.post(
            "/api/v1/message-test/assign",
            json={**ELIGIBLE, "access_key": other, "participant_token": token},
        )
        assert r.status_code == 403


class TestResponse:
    def _assign(self, client):
        return client.post("/api/v1/message-test/assign", json=ELIGIBLE).json()["participant_token"]

    def _payload(self, token, **over):
        base = {
            "access_key": KEY, "participant_token": token, "exposure_ms": 5000,
            "service_understanding": "나라장터 공고 옆에서 자격과 A값을 확인해 주는 서비스",
            "usage_moment": "투찰 전에 마지막으로 확인할 때",
            "checked_items": "참가조건과 낙찰하한선",
            "trust_score": 4, "relevance_score": 4,
        }
        base.update(over)
        return base

    def test_too_fast_is_rejected(self, client, live):
        """5초 화면을 건너뛴 응답은 받지 않는다(브라우저 값과 서버 경과 둘 다 본다)."""
        token = self._assign(client)
        r = client.post("/api/v1/message-test/responses", json=self._payload(token, exposure_ms=1000))
        assert r.status_code == 400

    def test_server_elapsed_guard_blocks_forged_exposure(self, client, live):
        """exposure_ms 를 조작해도 서버 경과 시간이 짧으면 막힌다."""
        token = self._assign(client)
        r = client.post("/api/v1/message-test/responses", json=self._payload(token, exposure_ms=9999))
        assert r.status_code == 400, "브라우저가 보낸 값만 믿고 통과시켰다"

    def test_duplicate_submission_is_idempotent(self, client, live, db_session, monkeypatch):
        from datetime import datetime, timedelta, timezone
        token = self._assign(client)
        row = (db_session.query(models.MessageTestParticipant)
               .filter_by(participant_token=token).one())
        row.assigned_at = datetime.now(timezone.utc) - timedelta(seconds=30)
        db_session.commit()

        first = client.post("/api/v1/message-test/responses", json=self._payload(token))
        assert first.status_code == 200 and first.json()["already_submitted"] is False
        second = client.post("/api/v1/message-test/responses", json=self._payload(token))
        assert second.status_code == 200 and second.json()["already_submitted"] is True


class TestCoding:
    """자동 1차 코딩 — 사람이 읽기 전에 기계가 먼저 센다."""

    def test_understands_all_four_codes(self):
        from app.api.v1.endpoints.message_validation import code_response
        out = code_response(
            "나라장터 공고를 볼 때 자격과 A값을 같은 화면에서 확인해 주는 서비스",
            "투찰 전에 마지막으로 점검할 때",
            "참가조건, 낙찰하한선",
        )
        assert out["codes_hit"] == 4
        assert out["prediction_misunderstood"] is False

    def test_flags_price_prediction_misunderstanding(self):
        """'낙찰가를 예측해 준다'고 읽었으면 포지션이 전달되지 않은 것이다."""
        from app.api.v1.endpoints.message_validation import code_response
        out = code_response("낙찰가를 예측해 주는 서비스", "입찰할 때", "예상 낙찰가")
        assert out["prediction_misunderstood"] is True


class TestGateSummary:
    """사전등록 게이트 — 표본 10 미만이면 어떤 경우도 통과하지 않는다."""

    def _rows(self, n, *, codes_hit=4, trust=5, misunderstood=0):
        from datetime import datetime, timezone
        out = []
        for i in range(n):
            out.append(models.MessageTestParticipant(
                participant_token=f"t{i}", campaign_key="c", cohort_key="k", variant="A",
                industry="전기공사", staff_count=3, directly_handles_bids=True,
                monthly_notice_reviews=20, submitted_at=datetime.now(timezone.utc),
                codes_hit=codes_hit, trust_score=trust,
                prediction_misunderstood=(i < misunderstood),
            ))
        return out

    def test_small_sample_never_passes(self):
        from app.api.v1.endpoints.message_validation import summarize_rows
        out = summarize_rows(self._rows(9))
        assert out["enough_sample"] is False and out["passed_gate"] is False

    def test_passes_when_all_criteria_met(self):
        from app.api.v1.endpoints.message_validation import summarize_rows
        assert summarize_rows(self._rows(10))["passed_gate"] is True

    def test_two_misunderstandings_block_the_gate(self):
        from app.api.v1.endpoints.message_validation import summarize_rows
        out = summarize_rows(self._rows(10, misunderstood=2))
        assert out["passed_gate"] is False, "낙찰가 예측 오해 2건이 게이트를 통과했다"
