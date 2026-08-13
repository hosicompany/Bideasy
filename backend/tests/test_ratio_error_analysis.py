"""사정률 예측 오차 분석 경로의 계약 회귀 테스트.

지키려는 것 넷 (전부 한 번 깨지면 결론이 조용히 뒤집히는 지점이다):

1. 오차 정의가 채점(`score_mock_bid`)과 갈라지지 않는다 — §P3.
2. 개선안의 margin 격자가 현행 2축 격자의 도달 범위를 **덮는다** — 안 덮으면
   개선안이 진 게 아니라 갈 수 있는 가격이 줄어서 진 것이 된다.
3. 사정률 중심 추정이 얕은 세그먼트에서 부모로 당겨진다 — 3건짜리 세그먼트의
   중앙값을 그대로 믿는 것이 곧 과적합이다.
4. oracle 은 진짜 하한이다 — 어떤 상수 예측도 이보다 낮은 MAE 를 못 낸다.
"""

import math

import pytest

from app.services.autocalibrate.dataset import BidRecord
from scripts import analyze_ratio_error as are


# 1억은 `get_bracket` 경계값이라 "small" 이 아니라 "medium" 이다(< 1e8 조건).
# 세그먼트를 명시하는 테스트에서 경계값을 쓰면 조용히 DEFAULT 로 떨어진다.
SMALL_BASIC = 50_000_000


def _record(bid_no="20260001-000", *, method="적격심사제", basic=SMALL_BASIC,
            reserved=None, winner=None, llr=89.745, year=2026):
    reserved = basic * 0.999 if reserved is None else reserved
    winner = basic * 0.90 if winner is None else winner
    return BidRecord(
        bid_no=bid_no, title="", org="", bid_method=method,
        basic_price=basic, estimated_price=basic, reserved_price=reserved,
        winner_price=winner, winner_rate=winner / basic * 100,
        lower_limit_rate=llr, year=year,
    )


class TestErrorDefinition:
    """채점과 같은 정의여야 한다 — 갈라지면 두 시스템이 다른 말을 한다."""

    def test_ratio_error_matches_scoring_formula(self):
        # score_mock_bid: ratio_error = |예정가격/기초금액 − (1+adj/100)|
        r = _record(basic=SMALL_BASIC, reserved=SMALL_BASIC * 0.992)
        params = {"적격심사제": {"small": [0.5, 1.0]}}

        t = are.tally([r], params)

        expected = abs(0.992 - (1 + 0.5 / 100))
        assert t["ratio_mae"] == pytest.approx(expected, abs=1e-9)

    def test_bias_is_signed_prediction_minus_actual(self):
        """부호가 뒤집히면 '높게 본다/낮게 본다' 진단이 정반대가 된다."""
        r = _record(basic=SMALL_BASIC, reserved=SMALL_BASIC * 0.99)
        params = {"적격심사제": {"small": [1.0, 1.0]}}  # 예측 1.010 > 실제 0.990

        t = are.tally([r], params)

        assert t["ratio_bias"] > 0

    def test_price_matches_evaluate_params_formula(self):
        r = _record(basic=SMALL_BASIC, llr=89.745)

        price = are.price_of(r, 0.5, 1.0)

        expected = math.floor(SMALL_BASIC * 1.005 * (89.745 + 1.0) / 100.0 / 10) * 10
        assert price == expected


class TestPinnedGridCoverage:
    """개선안이 현행보다 좁은 가격만 낼 수 있으면 비교 자체가 성립 안 한다."""

    @pytest.mark.parametrize("lower_rate", [85.495, 86.745, 87.745, 89.745])
    def test_grid_covers_two_axis_reachable_multipliers(self, lower_rate):
        two_axis = {
            (1 + a / 100.0) * (lower_rate + m)
            for a in are.GRID_ADJ for m in are.GRID_MARGIN
        }
        # 개선안은 adj 를 사정률 추정치(관측상 −1.0~+0.5%p)로 고정한다.
        for pinned in (-1.0, -0.1, 0.0, 0.5, 1.5):
            reachable = [
                (1 + pinned / 100.0) * (lower_rate + m)
                for m in are.pinned_margin_grid(0.1, pinned, lower_rate)
            ]
            assert min(reachable) <= min(two_axis)
            assert max(reachable) >= max(two_axis)

    def test_finer_step_yields_denser_grid(self):
        assert (len(are.pinned_margin_grid(0.02, -0.1, 89.745))
                > len(are.pinned_margin_grid(0.1, -0.1, 89.745)))


class TestRatioCenterFitting:
    def test_sparse_segment_shrinks_toward_parent(self):
        """3건짜리 세그먼트가 자기 중앙값을 그대로 갖지 않는다."""
        bulk = [
            _record(f"b{i}", method="적격심사제", basic=SMALL_BASIC,
                    reserved=SMALL_BASIC * 0.999)   # 부모 중심 ≈ 0.999
            for i in range(200)
        ]
        # xlarge 세그먼트 3건만 극단값 1.05
        odd = [
            _record(f"x{i}", method="적격심사제", basic=10_000_000_000,
                    reserved=10_500_000_000)
            for i in range(3)
        ]

        centers = are.fit_ratio_centers(bulk + odd)
        seg = centers["by_segment"][("적격심사제", "xxlarge")]

        assert seg < 1.05, "얕은 표본의 중앙값을 그대로 쓰면 과적합이다"
        assert seg == pytest.approx(1.0, abs=0.02)

    def test_pinned_adjustment_lands_on_grid_resolution(self):
        centers = {"global": 0.99873, "by_method": {}, "by_segment": {}}

        adj = are.pinned_adjustment(centers, "적격심사제", "small")

        assert adj == pytest.approx(-0.1)

    def test_unknown_segment_falls_back_to_method_then_global(self):
        centers = {
            "global": 0.990,
            "by_method": {"적격심사제": 0.995},
            "by_segment": {},
        }

        assert are.pinned_adjustment(centers, "적격심사제", "small") == pytest.approx(-0.5)
        assert are.pinned_adjustment(centers, "없는방법", "small") == pytest.approx(-1.0)


class TestOracleIsALowerBound:
    def test_no_constant_beats_the_oracle(self):
        recs = [
            _record(f"r{i}", basic=SMALL_BASIC,
                    reserved=SMALL_BASIC * (0.99 + i * 0.0004))
            for i in range(50)
        ]
        oracle = are.oracle_ratio_mae(recs)

        for pred in [0.98, 0.99, 0.995, 1.0, 1.005, 1.01]:
            mae = sum(abs(r.reserved_ratio - pred) for r in recs) / len(recs)
            assert mae >= oracle - 1e-9, f"{pred} 가 oracle 을 이겼다면 oracle 정의가 틀렸다"


class TestPromotionIsBlocked:
    """§P5 — 이 분석 경로는 전략을 승격하지 않는다."""

    def test_module_never_writes_to_the_strategy_store(self):
        src = (are.__file__ or "")
        with open(src, encoding="utf-8") as fh:
            body = fh.read()

        assert "commit(" not in body
        assert "save_active" not in body
        assert "promote" not in body
