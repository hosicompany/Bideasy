"""
smart-bid 엔드포인트 수습 회귀 테스트 (2026-07-18)
====================================================
- /recommend: 죽은 ML(numpy) → autocalibrate 룰기반 대체. 공사는 실동작,
  물품·용역은 정직한 503.
- ML 의존 엔드포인트: numpy/joblib 부재를 재현했을 때 500(에러 누출)이 아니라
  정직한 503 을 반환하는지 검증 (생산 환경 재현).
"""

import builtins

import pytest


@pytest.fixture(autouse=True)
def _verified_strategy_fixture(monkeypatch):
    """Endpoint success tests exercise the post-gate path explicitly."""
    from app.api.v1.endpoints import smart_bid

    monkeypatch.setattr(
        smart_bid,
        "_verified_strategy_deployment",
        lambda _db, *, rec, route: {
            "deployment_id": "deployment-test",
            "candidate_id": "candidate-test",
            "gate_decision_id": "gate-test",
            "approval_id": "approval-test",
            "data_manifest_hash": "d" * 64,
        },
    )


class TestRecommendRuleBased:
    def test_legacy_strategy_without_verified_lineage_abstains(
        self, pro_plus_client, monkeypatch
    ):
        from app.api.v1.endpoints import smart_bid

        monkeypatch.setattr(
            smart_bid,
            "_verified_strategy_deployment",
            lambda _db, *, rec, route: None,
        )
        response = pro_plus_client.post(
            "/api/v1/smart-bid/recommend",
            json={
                "base_amount": 100_000_000,
                "basis_status": "confirmed",
                "bid_type": "construction",
                "bid_no": "UNVERIFIED-1",
                "bid_method": "적격심사제",
                "a_value_status": "not_applicable",
                "lower_limit_rate": 89.745,
            },
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["decision_status"] == "abstained"
        assert data["abstain_code"] == "unverified_strategy_lineage"
        assert data["optimal_bid"] is None
        assert data["evidence"]["strategy_lineage_status"] == "UNVERIFIED"

    def test_construction_recommend_works(self, pro_plus_client, db_session):
        """공사 추천은 룰기반으로 실동작 — 안전선 응답."""
        res = pro_plus_client.post("/api/v1/smart-bid/recommend", json={
            "base_amount": 100_000_000,
            "basis_status": "confirmed",
            "bid_type": "construction",
            "bid_no": "TEST-1",
            "bid_method": "적격심사제",
            "a_value": 0,
            "a_value_status": "not_applicable",
            "lower_limit_rate": 89.745,
        })
        assert res.status_code == 200
        data = res.json()["data"]
        # Flutter SmartBidRecommendation 이 읽는 키들
        assert data["optimal_bid"] > 0
        assert data["lower_limit_pct"].endswith("%")
        assert data["effective_rate"] > 0
        assert data["expected_planned_price"]["mean"] > 0
        assert data["bid_rate"]["at_mean"] > 0
        assert data["tie_risk"] in ("high", "medium")
        # 정직 라벨: 예측 아님, 룰기반
        assert data["basis"] == "autocalibrate_rule_based"
        assert data["competition"] is None
        assert data["decision_status"] == "recommended"
        assert data["route"] == "QUALIFICATION"
        assert data["recommendation_id"]
        assert data["as_of"].endswith("Z")
        assert data["strategy_version"]
        assert data["abstain_reason"] is None
        assert data["probabilities"]["price_rank_one"] is None
        assert data["probabilities"]["unavailable_reason"]
        assert data["evidence"]["bid_no"] == "TEST-1"
        assert data["evidence"]["formula_hash"]
        # 추천가는 하한선 위 (무효 아님)
        assert data["optimal_bid"] >= data["danger_zone"]

        from app.db import models

        event = db_session.get(models.RecommendationEvent, data["recommendation_id"])
        assert event is not None
        assert event.notice_id == "TEST-1"
        assert event.user_id is not None
        assert event.route == "QUALIFICATION"
        assert event.policies[0]["name"] == "balanced"
        assert event.formula_hash == data["evidence"]["formula_hash"]
        assert event.strategy_version == data["strategy_version"]

    @pytest.mark.parametrize(
        ("a_value", "a_value_status"),
        [(1_000, "not_applicable"), (0, "confirmed")],
    )
    def test_contradictory_a_value_status_is_rejected(
        self, pro_plus_client, a_value, a_value_status
    ):
        response = pro_plus_client.post(
            "/api/v1/smart-bid/recommend",
            json={
                "base_amount": 100_000_000,
                "basis_status": "confirmed",
                "bid_type": "construction",
                "bid_method": "적격심사제",
                "lower_limit_rate": 89.745,
                "a_value": a_value,
                "a_value_status": a_value_status,
            },
        )

        assert response.status_code == 422

    def test_optimal_bid_above_lower_limit(self, pro_plus_client):
        """추천가는 언제나 낙찰하한선 위 — '잃지 않기' 보장."""
        res = pro_plus_client.post("/api/v1/smart-bid/recommend", json={
            "base_amount": 500_000_000,
            "basis_status": "confirmed",
            "bid_type": "construction",
            "bid_method": "적격심사제",
            "lower_limit_rate": 88.2,
            "a_value_status": "not_applicable",
        })
        assert res.status_code == 200
        data = res.json()["data"]
        # bid_rate(%) 는 하한율(%) 보다 커야 함
        lower_pct = float(data["lower_limit_pct"].rstrip("%"))
        assert data["bid_rate"]["at_mean"] >= lower_pct

    @pytest.mark.parametrize("bt", ["goods", "service"])
    def test_non_construction_explicit_abstain(self, pro_plus_client, bt):
        """물품·용역은 검증 표본 밖 — 오류가 아닌 명시적 기권 decision."""
        res = pro_plus_client.post("/api/v1/smart-bid/recommend", json={
            "base_amount": 100_000_000,
            "basis_status": "confirmed",
            "bid_type": bt,
            "bid_method": "적격심사제",
        })
        assert res.status_code == 200
        data = res.json()["data"]
        assert data["decision_status"] == "abstained"
        assert data["abstain_code"] == "unsupported_bid_type"
        assert data["optimal_bid"] is None
        assert data["route"] == "QUALIFICATION"

    def test_missing_bid_method_does_not_fall_back_to_default(
        self, pro_plus_client, db_session,
    ):
        res = pro_plus_client.post("/api/v1/smart-bid/recommend", json={
            "base_amount": 100_000_000,
            "basis_status": "confirmed",
            "bid_type": "construction",
        })
        assert res.status_code == 200
        data = res.json()["data"]
        assert data["decision_status"] == "abstained"
        assert data["abstain_code"] == "missing_bid_method"
        assert data["route"] == "UNSUPPORTED"

        from app.db import models

        event = db_session.get(models.RecommendationEvent, data["recommendation_id"])
        assert event is not None
        assert event.policies == []
        assert event.abstain_reason == data["abstain_reason"]

    def test_missing_bid_type_does_not_assume_construction(self, pro_plus_client):
        res = pro_plus_client.post("/api/v1/smart-bid/recommend", json={
            "base_amount": 100_000_000,
            "basis_status": "confirmed",
            "bid_method": "적격심사제",
        })
        assert res.status_code == 200
        data = res.json()["data"]
        assert data["decision_status"] == "abstained"
        assert data["abstain_code"] == "unsupported_bid_type"

    def test_unsupported_route_abstains_without_calling_calculator(
        self, pro_plus_client, monkeypatch,
    ):
        from app.services.calculator import CalculatorService

        def fail_if_called(**_kwargs):
            raise AssertionError("지원하지 않는 route가 DEFAULT 계산으로 흘렀다")

        monkeypatch.setattr(CalculatorService, "recommend_bid_price", fail_if_called)
        res = pro_plus_client.post("/api/v1/smart-bid/recommend", json={
            "base_amount": 100_000_000,
            "basis_status": "confirmed",
            "bid_type": "construction",
            "bid_method": "협상에의한계약",
        })
        assert res.status_code == 200
        data = res.json()["data"]
        assert data["decision_status"] == "abstained"
        assert data["route"] == "NEGOTIATION"

    def test_contract_method_route_cannot_be_bypassed_by_supported_bid_method(
        self, pro_plus_client, monkeypatch,
    ):
        from app.services.calculator import CalculatorService

        def fail_if_called(**_kwargs):
            raise AssertionError("협상 route가 적격심사 method로 우회했다")

        monkeypatch.setattr(CalculatorService, "recommend_bid_price", fail_if_called)
        res = pro_plus_client.post("/api/v1/smart-bid/recommend", json={
            "base_amount": 100_000_000,
            "basis_status": "confirmed",
            "bid_type": "construction",
            "bid_method": "적격심사제",
            "contract_method": "협상에 의한 계약",
            "lower_limit_rate": 89.745,
            "a_value_status": "not_applicable",
        })
        assert res.status_code == 200
        data = res.json()["data"]
        assert data["decision_status"] == "abstained"
        assert data["abstain_code"] == "unsupported_bid_method"
        assert data["route"] == "NEGOTIATION"

    def test_normalized_method_reaches_calculator(self, pro_plus_client, monkeypatch):
        from app.services.calculator import CalculatorService

        seen = {}
        original = CalculatorService.recommend_bid_price

        def capture(**kwargs):
            seen.update(kwargs)
            return original(**kwargs)

        monkeypatch.setattr(CalculatorService, "recommend_bid_price", capture)
        res = pro_plus_client.post("/api/v1/smart-bid/recommend", json={
            "base_amount": 100_000_000,
            "basis_status": "confirmed",
            "bid_type": "construction",
            "bid_method": "소액수의견적-소액수의견적(2인 이상 견적 제출)",
            "lower_limit_rate": 89.745,
            "a_value_status": "not_applicable",
        })
        assert res.status_code == 200
        assert seen["bid_method"] == "소액수의견적"
        assert seen["lower_limit_rate"] == 89.745
        assert res.json()["data"]["route"] == "PRICE_DOMINANT"

    def test_no_numpy_import_in_recommend(self, pro_plus_client, monkeypatch):
        """/recommend 는 numpy 없이도 동작해야 한다 (생산 환경 재현)."""
        real_import = builtins.__import__

        def blocked_import(name, *args, **kwargs):
            if name == "numpy" or name.startswith("numpy."):
                raise ModuleNotFoundError("No module named 'numpy'")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", blocked_import)
        res = pro_plus_client.post("/api/v1/smart-bid/recommend", json={
            "base_amount": 100_000_000,
            "basis_status": "confirmed",
            "bid_type": "construction",
            "bid_method": "적격심사제",
            "lower_limit_rate": 89.745,
            "a_value_status": "not_applicable",
        })
        assert res.status_code == 200  # numpy 안 써도 정상

    def test_notice_formula_inputs_drive_price_and_flutter_rate(
        self, pro_plus_client,
    ):
        """공고 하한율·A값·예정가 범위가 같은 공식으로 연결된다."""
        from app.services.calculator import CalculatorService

        res = pro_plus_client.post("/api/v1/smart-bid/recommend", json={
            "base_amount": 100_000_000,
            "basis_status": "CONFIRMED",
            "bid_type": "construction",
            "bid_no": "FORMULA-1",
            "bid_method": "적격심사제",
            "a_value": 10_000_000,
            "a_value_status": "confirmed",
            "lower_limit_rate": 88.2,
            "bid_date": "2026-02-01",
            "prdprc_range_bgn": -2,
            "prdprc_range_end": 2,
        })
        assert res.status_code == 200
        data = res.json()["data"]

        assert data["decision_status"] == "recommended"
        assert data["lower_limit"] == 0.882
        assert data["lower_limit_pct"] == "88.200%"
        assert data["evidence"]["lower_limit_source"] == "notice"
        assert data["expected_planned_price"]["range"] == {
            "low": 98_000_000,
            "high": 102_000_000,
            "source": "notice_public_range",
            "unavailable_reason": None,
        }

        # Flutter가 at_mean-100을 동일 A값 공식에 넣으면 추천가가 재현된다.
        applied_rate = data["bid_rate"]["at_mean"] - 100
        reproduced = CalculatorService.calculate_safe_bid(
            100_000_000,
            applied_rate,
            10_000_000,
        )
        assert reproduced == data["optimal_bid"]
        assert data["optimal_bid"] % 10 == 0
        assert data["danger_zone"] % 10 == 0

        predicted = data["expected_planned_price"]["mean"]
        expected_danger = CalculatorService.calculate_price_at_rate(
            predicted,
            88.2,
            10_000_000,
        )
        assert data["danger_zone"] == expected_danger
        assert data["optimal_bid"] >= data["danger_zone"]

    def test_missing_public_range_is_null_with_reason(self, pro_plus_client):
        res = pro_plus_client.post("/api/v1/smart-bid/recommend", json={
            "base_amount": 100_000_000,
            "basis_status": "confirmed",
            "bid_type": "construction",
            "bid_method": "적격심사제",
            "lower_limit_rate": 89.745,
            "a_value_status": "not_applicable",
        })
        assert res.status_code == 200
        price_range = res.json()["data"]["expected_planned_price"]["range"]
        assert price_range["low"] is None
        assert price_range["high"] is None
        assert price_range["source"] is None
        assert price_range["unavailable_reason"]

    def test_bid_date_selects_versioned_lower_limit_when_notice_rate_missing(
        self, pro_plus_client,
    ):
        res = pro_plus_client.post("/api/v1/smart-bid/recommend", json={
            "base_amount": 100_000_000,
            "basis_status": "confirmed",
            "bid_type": "construction",
            "bid_method": "적격심사제",
            "bid_date": "2026-02-01",
            "a_value_status": "not_applicable",
        })
        assert res.status_code == 200
        data = res.json()["data"]
        assert data["decision_status"] == "recommended"
        assert data["lower_limit_pct"] == "89.745%"
        assert data["evidence"]["lower_limit_source"] == "versioned_rule_table"

    def test_missing_lower_limit_and_date_abstains(self, pro_plus_client):
        res = pro_plus_client.post("/api/v1/smart-bid/recommend", json={
            "base_amount": 100_000_000,
            "basis_status": "confirmed",
            "bid_type": "construction",
            "bid_method": "적격심사제",
        })
        assert res.status_code == 200
        data = res.json()["data"]
        assert data["decision_status"] == "abstained"
        assert data["abstain_code"] == "missing_lower_limit_context"

    @pytest.mark.parametrize("extra", [
        {"a_value": 100_000_000, "lower_limit_rate": 89.745},
        {
            "lower_limit_rate": 89.745,
            "prdprc_range_bgn": -2,
        },
        {
            "lower_limit_rate": 89.745,
            "prdprc_range_bgn": 2,
            "prdprc_range_end": -2,
        },
    ])
    def test_invalid_formula_context_is_rejected(self, pro_plus_client, extra):
        res = pro_plus_client.post("/api/v1/smart-bid/recommend", json={
            "base_amount": 100_000_000,
            "basis_status": "confirmed",
            "bid_type": "construction",
            "bid_method": "적격심사제",
            **extra,
        })
        assert res.status_code == 422

    @pytest.mark.parametrize("payload", [
        {"base_amount": 100_000_000},
        {"base_amount": None, "basis_status": "unconfirmed"},
    ])
    def test_unconfirmed_basis_abstains_before_calculation(
        self, pro_plus_client, monkeypatch, payload,
    ):
        from app.services.calculator import CalculatorService

        def fail_if_called(**_kwargs):
            raise AssertionError("미확인 기초금액으로 계산했다")

        monkeypatch.setattr(CalculatorService, "recommend_bid_price", fail_if_called)
        res = pro_plus_client.post("/api/v1/smart-bid/recommend", json={
            **payload,
            "bid_type": "construction",
            "bid_method": "적격심사제",
        })
        assert res.status_code == 200
        data = res.json()["data"]
        assert data["decision_status"] == "abstained"
        assert data["abstain_code"] == "unconfirmed_basis_amount"


class TestMLEndpointsGracefulDegrade:
    """numpy/joblib 부재(생산 환경)에서 500 누출이 아니라 정직한 503."""

    @pytest.fixture
    def block_ml_imports(self, monkeypatch):
        real_import = builtins.__import__
        blocked = ("numpy", "joblib", "sklearn")

        def blocked_import(name, *args, **kwargs):
            root = name.split(".")[0]
            if root in blocked:
                raise ModuleNotFoundError(f"No module named '{root}'")
            return real_import(name, *args, **kwargs)

        # 캐시된 서비스 싱글턴 초기화 (이전 테스트에서 로드됐을 수 있음)
        import app.services.participant_prediction_service as pps
        import app.services.bidrate_prediction_service as bps
        monkeypatch.setattr(pps, "_service", None, raising=False)
        monkeypatch.setattr(bps, "_service", None, raising=False)
        monkeypatch.setattr(builtins, "__import__", blocked_import)

    def test_competition_predict_503_not_500(self, pro_client, block_ml_imports):
        res = pro_client.post("/api/v1/smart-bid/competition/predict", json={
            "bid_type": "construction", "estimated_amount": 100_000_000,
        })
        assert res.status_code == 503
        # 내부 에러 문자열(모듈명 등) 누출 금지
        assert "numpy" not in res.text and "joblib" not in res.text

    def test_rate_predict_503_not_500(self, pro_plus_client, block_ml_imports):
        res = pro_plus_client.post("/api/v1/smart-bid/rate/predict", json={
            "bid_type": "goods", "estimated_amount": 100_000_000,
            "expected_participants": 10,
        })
        assert res.status_code == 503
        assert "joblib" not in res.text and "numpy" not in res.text

    def test_agency_stats_503_not_500(self, client, block_ml_imports):
        res = client.get("/api/v1/smart-bid/agency/stats?bid_type=construction")
        assert res.status_code == 503
        assert "joblib" not in res.text and "numpy" not in res.text
