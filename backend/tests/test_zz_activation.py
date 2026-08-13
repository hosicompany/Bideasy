"""활성화 계측 테스트.

- PUT /api/v1/users/me · POST /api/v1/auth/register — 프로필 완성(면허+소재지) 1회 기록
- GET /api/v1/ai/{bid_no}/analysis — 첫 안전 판정 1회 기록 (성공 응답만 — 400 은 미기록)
- POST /api/v1/bids/calculate·/calculate/detailed — 첫 안전 판정 기록 + 익명·위조 토큰 불변
- GET /api/v1/admin/stats/activation — 응답 스키마 + 비관리자 403
- services/activation.record_first_activation — best-effort 계약 (DB 실패가 전파되지 않음)

기존 free_client/admin_client 등 공유 픽스처의 기본 사용자는 다른 테스트 파일에서도
재사용되므로(세션 스코프 engine), 이 파일에서 프로필·활성화 상태를 뒤바꾸는 테스트는
전용 이메일로 새 사용자를 직접 만들어 부작용을 격리한다 (test_ai_analysis.py 의
test_qualification_not_leaked_via_cache 와 같은 패턴).
"""
from datetime import datetime, timezone

import pytest

from app.core.rate_limit import limiter
from app.core.security import create_access_token
from app.db import models
from app.services.activation import record_first_activation


@pytest.fixture(autouse=True)
def _disable_rate_limiter():
    """AI 분석·가입 호출이 레이트리밋에 걸리지 않도록. teardown 은 원래 값 복원 —
    False 로 고정하면 뒤에 오는 파일의 레이트리밋 테스트를 조용히 무력화한다."""
    prev = limiter.enabled
    limiter.enabled = False
    yield
    limiter.enabled = prev


def _make_user(db_session, email, **kwargs):
    user = models.User(email=email, hashed_password="x", tier=kwargs.pop("tier", "pro"), **kwargs)
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def _auth_headers(user) -> dict:
    token = create_access_token({"sub": str(user.id)})
    return {"Authorization": f"Bearer {token}"}


class TestProfileCompleteHook:
    """PUT /api/v1/users/me — 프로필 완성 계측."""

    def test_licenses_and_location_records_once(self, client, db_session):
        user = _make_user(db_session, "activation-profile-1@test.com")
        headers = _auth_headers(user)

        resp = client.put(
            "/api/v1/users/me",
            json={"licenses": "전기공사업", "location": "서울특별시"},
            headers=headers,
        )
        assert resp.status_code == 200

        db_session.refresh(user)
        assert user.profile_completed_at is not None
        first_ts = user.profile_completed_at

        # 재갱신(내용 변경)에도 최초 기록 시각은 불변
        resp2 = client.put(
            "/api/v1/users/me",
            json={"licenses": "전기공사업,기계설비공사업", "location": "부산광역시"},
            headers=headers,
        )
        assert resp2.status_code == 200
        db_session.refresh(user)
        assert user.profile_completed_at == first_ts

    def test_profile_cleared_does_not_revert_timestamp(self, client, db_session):
        """완성 기록 후 프로필을 비워도 profile_completed_at 은 되돌아가지 않는다."""
        user = _make_user(db_session, "activation-profile-2@test.com")
        headers = _auth_headers(user)

        client.put(
            "/api/v1/users/me",
            json={"licenses": "전기공사업", "location": "서울특별시"},
            headers=headers,
        )
        db_session.refresh(user)
        first_ts = user.profile_completed_at
        assert first_ts is not None

        client.put("/api/v1/users/me", json={"licenses": "", "location": ""}, headers=headers)
        db_session.refresh(user)
        assert user.profile_completed_at == first_ts

    def test_licenses_only_without_location_not_recorded(self, client, db_session):
        user = _make_user(db_session, "activation-profile-3@test.com")
        headers = _auth_headers(user)

        resp = client.put(
            "/api/v1/users/me",
            json={"licenses": "전기공사업"},
            headers=headers,
        )
        assert resp.status_code == 200
        db_session.refresh(user)
        assert user.profile_completed_at is None

    def test_location_only_without_licenses_not_recorded(self, client, db_session):
        user = _make_user(db_session, "activation-profile-4@test.com")
        headers = _auth_headers(user)

        resp = client.put(
            "/api/v1/users/me",
            json={"location": "서울특별시"},
            headers=headers,
        )
        assert resp.status_code == 200
        db_session.refresh(user)
        assert user.profile_completed_at is None


class TestFirstActivationHookAiAnalysis:
    """GET /api/v1/ai/{bid_no}/analysis — 첫 안전 판정 계측."""

    def test_first_call_records_activation(self, client, db_session, sample_notice, monkeypatch):
        monkeypatch.setattr(
            "app.services.scraper.ScraperService.fetch_page_content",
            lambda url: None,
        )
        user = _make_user(db_session, "activation-ai-1@test.com")
        headers = _auth_headers(user)
        assert user.first_activation_at is None

        resp = client.get(
            "/api/v1/ai/TEST-001/analysis",
            params={
                "title": "서울시 강남구 구민회관 리모델링 공사",
                "basic_price": 500000000,
                "organization": "강남구청",
                "contract_type": "CONSTRUCTION",
            },
            headers=headers,
        )
        assert resp.status_code == 200
        db_session.refresh(user)
        assert user.first_activation_at is not None

    def test_second_call_does_not_change_timestamp(self, client, db_session, sample_notice, monkeypatch):
        monkeypatch.setattr(
            "app.services.scraper.ScraperService.fetch_page_content",
            lambda url: None,
        )
        user = _make_user(db_session, "activation-ai-2@test.com")
        headers = _auth_headers(user)
        params = {
            "title": "서울시 강남구 구민회관 리모델링 공사",
            "basic_price": 500000000,
            "organization": "강남구청",
            "contract_type": "CONSTRUCTION",
        }

        r1 = client.get("/api/v1/ai/TEST-001/analysis", params=params, headers=headers)
        assert r1.status_code == 200
        db_session.refresh(user)
        first_ts = user.first_activation_at
        assert first_ts is not None

        r2 = client.get("/api/v1/ai/TEST-001/analysis", params=params, headers=headers)
        assert r2.status_code == 200
        db_session.refresh(user)
        assert user.first_activation_at == first_ts

    def test_cache_hit_also_records(self, client, db_session, sample_notice, monkeypatch):
        """캐시 히트 경로도 사용자에겐 성공한 분석 — 활성화로 기록돼야 한다."""
        monkeypatch.setattr(
            "app.services.scraper.ScraperService.fetch_page_content",
            lambda url: None,
        )
        params = {
            "title": "서울시 강남구 구민회관 리모델링 공사",
            "basic_price": 500000000,
            "organization": "강남구청",
            "contract_type": "CONSTRUCTION",
        }
        # user_a 의 첫 호출이 AIAnalysisLog 캐시를 만든다
        user_a = _make_user(db_session, "activation-ai-cache-a@test.com")
        r1 = client.get("/api/v1/ai/TEST-001/analysis", params=params, headers=_auth_headers(user_a))
        assert r1.status_code == 200

        # user_b 의 첫 호출은 캐시 히트로 조기 반환된다 — 그래도 기록돼야 한다
        user_b = _make_user(db_session, "activation-ai-cache-b@test.com")
        r2 = client.get("/api/v1/ai/TEST-001/analysis", params=params, headers=_auth_headers(user_b))
        assert r2.status_code == 200
        db_session.refresh(user_b)
        assert user_b.first_activation_at is not None

    def test_failed_analysis_does_not_record(self, client, db_session):
        """400(정보 부족)으로 끝난 요청은 활성화로 세지 않는다 — 훅은 성공 응답 직전에만."""
        user = _make_user(db_session, "activation-ai-fail@test.com")
        resp = client.get("/api/v1/ai/NO-SUCH-BID/analysis", headers=_auth_headers(user))
        assert resp.status_code == 400
        db_session.refresh(user)
        assert user.first_activation_at is None


class TestFirstActivationHookCalculator:
    """POST /api/v1/bids/calculate·/calculate/detailed — 첫 안전 판정 계측.

    실사용 트래픽은 /calculate/detailed 로 온다(공고상세 SSR·Flutter) — 훅이 거기
    없으면 지표가 "AI 분석을 눌러본 사람"만 세게 되므로 두 경로 모두 검증한다.
    """

    _PAYLOAD = {
        "basic_price": 100000000,
        "a_value": 0,
        "a_value_status": "not_applicable",
        "rate": -2.0,
    }

    def test_detailed_records_activation(self, client, db_session):
        user = _make_user(db_session, "activation-calc-1@test.com")
        resp = client.post(
            "/api/v1/bids/calculate/detailed", json=self._PAYLOAD, headers=_auth_headers(user)
        )
        assert resp.status_code == 200
        db_session.refresh(user)
        assert user.first_activation_at is not None

    def test_basic_calculate_records_activation(self, client, db_session):
        user = _make_user(db_session, "activation-calc-2@test.com")
        resp = client.post(
            "/api/v1/bids/calculate", json=self._PAYLOAD, headers=_auth_headers(user)
        )
        assert resp.status_code == 200
        db_session.refresh(user)
        assert user.first_activation_at is not None

    def test_anonymous_calculate_unchanged(self, client):
        """익명 계산은 이 PR 이전과 동일하게 200 — 계측이 공개 계산기를 막지 않는다."""
        for path in ("/api/v1/bids/calculate", "/api/v1/bids/calculate/detailed"):
            resp = client.post(path, json=self._PAYLOAD)
            assert resp.status_code == 200, path

    def test_invalid_token_treated_as_anonymous(self, client):
        """위조·만료 토큰은 401 이 아니라 익명으로 처리된다(get_current_user_optional 계약)."""
        headers = {"Authorization": "Bearer this-is-not-a-jwt"}
        for path in ("/api/v1/bids/calculate", "/api/v1/bids/calculate/detailed"):
            resp = client.post(path, json=self._PAYLOAD, headers=headers)
            assert resp.status_code == 200, path


class TestBestEffortContract:
    """record_first_activation 은 DB 가 어떤 식으로 죽어도 예외를 전파하지 않는다."""

    class _User:
        id = 1
        first_activation_at = None

    def test_broken_add_does_not_raise(self):
        class _BrokenDB:
            def add(self, obj):
                raise RuntimeError("db down")

            def rollback(self):
                pass

        record_first_activation(_BrokenDB(), self._User(), source="test")

    def test_broken_rollback_does_not_raise(self):
        class _BrokenDB:
            def add(self, obj):
                raise RuntimeError("db down")

            def rollback(self):
                raise RuntimeError("rollback also down")

        record_first_activation(_BrokenDB(), self._User(), source="test")

    def test_none_user_is_noop(self):
        class _MustNotTouch:
            def add(self, obj):
                raise AssertionError("익명 요청에서 DB 를 건드리면 안 된다")

        record_first_activation(_MustNotTouch(), None, source="test")


class TestRegisterActivation:
    """POST /api/v1/auth/register — 가입 시점 계측."""

    def test_register_fills_created_at(self, client, db_session):
        resp = client.post(
            "/api/v1/auth/register",
            json={"email": "activation-reg-1@test.com", "password": "password123"},
        )
        assert resp.status_code == 200
        user = (
            db_session.query(models.User)
            .filter(models.User.email == "activation-reg-1@test.com")
            .first()
        )
        assert user is not None
        assert user.created_at is not None
        assert user.profile_completed_at is None  # 프로필 없이 가입 — 미완성

    def test_register_with_full_profile_records_completion(self, client, db_session):
        """가입 폼에서 면허·소재지를 함께 채우면 PUT /users/me 없이도 완성으로 기록."""
        resp = client.post(
            "/api/v1/auth/register",
            json={
                "email": "activation-reg-2@test.com",
                "password": "password123",
                "licenses": "전기공사업",
                "location": "서울특별시",
            },
        )
        assert resp.status_code == 200
        user = (
            db_session.query(models.User)
            .filter(models.User.email == "activation-reg-2@test.com")
            .first()
        )
        assert user is not None
        assert user.profile_completed_at is not None


class TestAdminActivationStats:
    """GET /api/v1/admin/stats/activation."""

    def test_non_admin_forbidden(self, free_client):
        resp = free_client.get("/api/v1/admin/stats/activation")
        assert resp.status_code == 403

    def test_anonymous_unauthorized(self, client):
        resp = client.get("/api/v1/admin/stats/activation")
        assert resp.status_code == 401

    def test_response_schema(self, admin_client):
        resp = admin_client.get("/api/v1/admin/stats/activation")
        assert resp.status_code == 200
        data = resp.json()
        for key in (
            "total_users", "with_created_at", "profile_complete", "profile_complete_pct",
            "activated", "activated_pct", "daily",
        ):
            assert key in data
        assert isinstance(data["daily"], list)
        if data["daily"]:
            point = data["daily"][0]
            # cohort_* — 일별 시리즈는 이벤트 발생일이 아니라 가입일(코호트) 기준이다
            for key in ("date", "signups", "cohort_profile_complete", "cohort_activated"):
                assert key in point

    def test_pct_uses_with_created_at_as_denominator(self, admin_client, db_session):
        """계측 이전(created_at=NULL) 레거시 사용자는 분모에서 제외된다."""
        base = admin_client.get("/api/v1/admin/stats/activation").json()

        # 계측 이전 가입자 시뮬레이션 — insert 후 UPDATE 로 created_at 을 NULL 화
        # (Column default 는 INSERT 시에만 적용되고 UPDATE 시에는 적용되지 않는다).
        legacy = _make_user(db_session, "activation-legacy@test.com")
        legacy.profile_completed_at = datetime.now(timezone.utc)
        legacy.created_at = None
        db_session.add(legacy)
        db_session.commit()

        after_legacy = admin_client.get("/api/v1/admin/stats/activation").json()
        # 레거시 사용자는 total_users 는 늘리지만 with_created_at/profile_complete 는 불변
        assert after_legacy["total_users"] == base["total_users"] + 1
        assert after_legacy["with_created_at"] == base["with_created_at"]
        assert after_legacy["profile_complete"] == base["profile_complete"]

        # 계측 대상(신규) 가입자 — 프로필 완성까지
        new_user = _make_user(db_session, "activation-new@test.com")
        new_user.profile_completed_at = datetime.now(timezone.utc)
        db_session.add(new_user)
        db_session.commit()

        after_new = admin_client.get("/api/v1/admin/stats/activation").json()
        assert after_new["with_created_at"] == after_legacy["with_created_at"] + 1
        assert after_new["profile_complete"] == after_legacy["profile_complete"] + 1
        expected_pct = round(
            after_new["profile_complete"] / after_new["with_created_at"] * 100, 1
        )
        assert after_new["profile_complete_pct"] == expected_pct
