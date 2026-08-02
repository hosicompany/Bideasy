"""과거 5-arm 백테스트 테스트.

지키려는 것:
1. 판정이 mock_bidding.judge 와 갈라지지 않는다 (§P3 판정 단일 소스)
2. 응답이 caveats 를 항상 실어 보낸다 — 화면이 "이건 사후 재구성"이라는
   경고를 빠뜨릴 수 없게 하기 위함
3. 파라미터를 못 구한 arm 을 지어내지 않는다
"""
import math

import pytest

from app.services import arm_backtest as ab
from app.services.autocalibrate.dataset import BidRecord
from app.services.mock_bidding import judge


def _rec(bid_no="X", basic=100_000_000, reserved=100_000_000,
         winner=92_000_000, llr=87.745, method="적격심사제", year=2025):
    return BidRecord(
        bid_no=bid_no, title="", org="", bid_method=method,
        basic_price=basic, estimated_price=basic, reserved_price=reserved,
        winner_price=winner, winner_rate=winner / basic * 100,
        lower_limit_rate=llr, year=year,
    )


class TestWilsonCI:
    def test_zero_sample(self):
        assert ab.wilson_ci(0, 0) == (0.0, 0.0)

    def test_bounds_within_0_100(self):
        lo, hi = ab.wilson_ci(5, 10)
        assert 0.0 <= lo <= hi <= 100.0

    def test_small_sample_is_wider(self):
        """표본이 작으면 구간이 넓어야 한다 — 우열 단정을 막는 근거."""
        n_lo, n_hi = ab.wilson_ci(50, 100)
        w_lo, w_hi = ab.wilson_ci(500, 1000)
        assert (n_hi - n_lo) > (w_hi - w_lo)


class TestPricing:
    def test_flat_matches_calculator(self):
        """price_flat 은 calculator.calculate_safe_bid(a_value=0) 와 같아야 한다."""
        from app.services.calculator import CalculatorService

        r = _rec(basic=100_000_000)
        assert ab.price_flat(r, -2.5) == CalculatorService.calculate_safe_bid(
            r.basic_price, -2.5, 0)

    def test_params_matches_simulate_params_formula(self):
        """price_params 는 optimizer.simulate_params 의 가격 공식과 같아야 한다."""
        r = _rec()
        params = {"적격심사제": {"medium": [-0.5, 1.0]}}
        adj, margin = -0.5, 1.0
        expected = math.floor(
            r.basic_price * (1 + adj / 100.0) * (r.lower_limit_rate + margin) / 100.0 / 10
        ) * 10
        assert ab.price_params(r, params) == expected

    def test_params_falls_back_to_default(self):
        r = _rec(method="알수없는방법")
        params = {"DEFAULT": {"medium": [0.0, 1.0]}}
        assert ab.price_params(r, params) > 0


class TestTallyMatchesJudge:
    def test_dropout_counted(self):
        """하한선 미만은 무효로 잡힌다."""
        r = _rec(reserved=100_000_000, llr=87.745, winner=92_000_000)
        res = ab.tally([r], lambda _r: 80_000_000)   # 하한선 87,745,000 미만
        assert res["dropout_rate"] == 100.0
        assert res["win_rate"] == 0.0

    def test_win_counted(self):
        r = _rec(reserved=100_000_000, llr=87.745, winner=92_000_000)
        res = ab.tally([r], lambda _r: 90_000_000)   # [87.745M, 92M] 구간
        assert res["win_rate"] == 100.0

    def test_lost_counted(self):
        r = _rec(reserved=100_000_000, llr=87.745, winner=92_000_000)
        res = ab.tally([r], lambda _r: 95_000_000)   # 낙찰가 초과
        assert res["lost_rate"] == 100.0
        assert res["win_rate"] == 0.0

    def test_agrees_with_judge_directly(self):
        """tally 의 분류가 mock_bidding.judge 와 건별로 일치해야 한다."""
        recs = [
            _rec("A", winner=92_000_000),
            _rec("B", winner=88_000_000),
            _rec("C", reserved=103_000_000, winner=95_000_000),
        ]
        price_fn = lambda r: 90_000_000  # noqa: E731
        got = ab.tally(recs, price_fn)

        wins = sum(
            1 for r in recs
            if judge(price_fn(r), r.reserved_price * r.lower_limit_rate / 100.0,
                     r.winner_price) == "WIN"
        )
        assert got["win_rate"] == pytest.approx(wins / len(recs) * 100, abs=0.01)

    def test_rates_sum_to_100(self):
        recs = [_rec("A"), _rec("B", winner=85_000_000), _rec("C", winner=99_000_000)]
        m = ab.tally(recs, lambda _r: 90_000_000)
        assert m["win_rate"] + m["dropout_rate"] + m["lost_rate"] == pytest.approx(100.0, abs=0.01)


class TestBuildArms:
    def test_flat_arms_always_present(self):
        """standard·aggressive 는 외부 파라미터가 없어도 항상 만들 수 있다."""
        arms = ab.build_arms()
        assert "standard" in arms and "aggressive" in arms

    def test_order_is_fixed(self):
        """표·차트의 arm 순서가 실행마다 흔들리면 안 된다."""
        arms = ab.build_arms()
        assert list(arms.keys()) == [a for a in ab.ARM_ORDER if a in arms]

    def test_flat_arm_prices(self):
        arms = ab.build_arms()
        r = _rec(basic=100_000_000)
        assert arms["standard"](r) == 97_500_000
        assert arms["aggressive"](r) == 88_000_000


class TestRun:
    def test_returns_caveats(self):
        """화면이 «사후 재구성» 경고를 빠뜨릴 수 없도록 응답에 항상 싣는다."""
        res = ab.run()
        if not res.get("available"):
            pytest.skip("과거 데이터 파일 없음")
        assert res["caveats"]
        joined = " ".join(res["caveats"])
        assert "증거가 아니" in joined      # 백테스트의 한계 명시
        assert "holdout" in joined          # frontier 편향 경고

    def test_slices_and_arms(self):
        res = ab.run()
        if not res.get("available"):
            pytest.skip("과거 데이터 파일 없음")
        assert res["n_records"] > 0
        assert set(res["slice_sizes"]) >= {"overall", "holdout"}
        for name, e in res["arms"].items():
            assert "desc" in e
            assert e["overall"]["n"] > 0

    def test_unknown_method_filter_is_graceful(self):
        res = ab.run(bid_method="존재하지않는방법")
        assert res["available"] is False
        assert res["arms"] == {}
