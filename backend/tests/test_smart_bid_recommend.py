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


class TestRecommendRuleBased:
    def test_construction_recommend_works(self, pro_plus_client):
        """공사 추천은 룰기반으로 실동작 — 안전선 응답."""
        res = pro_plus_client.post("/api/v1/smart-bid/recommend", json={
            "base_amount": 100_000_000,
            "bid_type": "construction",
            "a_value": 0,
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
        # 추천가는 하한선 위 (무효 아님)
        assert data["optimal_bid"] >= data["danger_zone"]

    def test_optimal_bid_above_lower_limit(self, pro_plus_client):
        """추천가는 언제나 낙찰하한선 위 — '잃지 않기' 보장."""
        res = pro_plus_client.post("/api/v1/smart-bid/recommend", json={
            "base_amount": 500_000_000, "bid_type": "construction",
        })
        assert res.status_code == 200
        data = res.json()["data"]
        # bid_rate(%) 는 하한율(%) 보다 커야 함
        lower_pct = float(data["lower_limit_pct"].rstrip("%"))
        assert data["bid_rate"]["at_mean"] >= lower_pct

    @pytest.mark.parametrize("bt", ["goods", "service"])
    def test_non_construction_honest_503(self, pro_plus_client, bt):
        """물품·용역은 검증 표본 밖 — 정직한 503 (가짜 추천 금지)."""
        res = pro_plus_client.post("/api/v1/smart-bid/recommend", json={
            "base_amount": 100_000_000, "bid_type": bt,
        })
        assert res.status_code == 503

    def test_no_numpy_import_in_recommend(self, pro_plus_client, monkeypatch):
        """/recommend 는 numpy 없이도 동작해야 한다 (생산 환경 재현)."""
        real_import = builtins.__import__

        def blocked_import(name, *args, **kwargs):
            if name == "numpy" or name.startswith("numpy."):
                raise ModuleNotFoundError("No module named 'numpy'")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", blocked_import)
        res = pro_plus_client.post("/api/v1/smart-bid/recommend", json={
            "base_amount": 100_000_000, "bid_type": "construction",
        })
        assert res.status_code == 200  # numpy 안 써도 정상


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
