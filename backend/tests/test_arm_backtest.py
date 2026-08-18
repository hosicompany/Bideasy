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
from app.services.autocalibrate import dataset as ds
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


class TestBaseConsistencyGuard:
    """금액 기준(부가세 포함 여부)이 섞인 행을 걸러내는 가드.

    2026-08-03 실측: 개찰 크롤러가 `presmptPrce`(부가세 제외)를 basic_price 로
    저장해, 운영 DB 행 97건 중 93건의 사정률이 1.10 부근이었다. 이 행을 섞어
    집계하니 active 무효율이 5% → 50% 로 튀었다. 가드가 없으면 화면이 전략
    실패로 오독된다.
    """

    def test_normal_ratio_passes(self):
        assert ab.base_is_consistent(_rec(basic=100_000_000, reserved=100_500_000))

    def test_vat_excluded_basic_is_rejected(self):
        """예정가격 ÷ 기초금액 ≈ 1.1 = 부가세 기준이 다른 행."""
        assert not ab.base_is_consistent(_rec(basic=100_000_000, reserved=110_000_000))

    def test_zero_price_is_rejected(self):
        """0 으로 나누지 않고 조용히 거른다."""
        zero_basic = BidRecord(
            bid_no="Z1", title="", org="", bid_method="적격심사제",
            basic_price=0, estimated_price=0, reserved_price=100_000_000,
            winner_price=92_000_000, winner_rate=0, lower_limit_rate=87.745, year=2025,
        )
        assert not ab.base_is_consistent(zero_basic)
        assert not ab.base_is_consistent(_rec(basic=100_000_000, reserved=0))

    def test_static_dataset_all_passes(self):
        """정본 정적 데이터는 한 건도 걸러지면 안 된다 — 밴드가 좁으면 실측이 사라진다."""
        recs, stats = ds.load_records_with_stats(db=None)
        if not recs:
            pytest.skip("정적 개찰 데이터 없음")
        # 걸러진 결과의 all() 은 항진명제 — 필터 전 대비 제외 0 을 단언한다
        assert stats.excluded_base_inconsistent == 0

    def test_run_excludes_and_reports_count(self, monkeypatch):
        """제외는 하되 **몇 건인지 반드시 알린다** — 조용한 절삭 금지."""
        good = [_rec(f"G{i}", basic=100_000_000, reserved=100_500_000) for i in range(60)]
        bad = [_rec(f"B{i}", basic=100_000_000, reserved=110_000_000) for i in range(40)]
        monkeypatch.setattr(ab.ds, "load_records_with_stats", lambda db=None, **k: (good + bad, ab.ds.LoadStats(loaded=100, kept=100)))

        res = ab.run()
        assert res["available"] is True
        assert res["n_loaded"] == 100
        assert res["n_records"] == 60
        assert res["n_excluded_base_mismatch"] == 40
        assert any("40" in c and "제외" in c for c in res["caveats"])

    def test_run_unavailable_when_all_mismatched(self, monkeypatch):
        bad = [_rec(f"B{i}", basic=100_000_000, reserved=110_000_000) for i in range(10)]
        monkeypatch.setattr(ab.ds, "load_records_with_stats", lambda db=None, **k: (bad, ab.ds.LoadStats(loaded=10, kept=10)))
        res = ab.run()
        assert res["available"] is False
        assert "10" in res["reason"]


class TestMethodBreakdown:
    """'전체' 한 칸이 낙찰하한 체계가 다른 방법들을 뭉개는 것을 드러내기 위함."""

    def test_by_method_present_for_large_methods(self, monkeypatch):
        a = [_rec(f"A{i}", method="적격심사제") for i in range(ab.MIN_METHOD_N)]
        b = [_rec(f"B{i}", method="소액수의견적") for i in range(ab.MIN_METHOD_N)]
        monkeypatch.setattr(ab.ds, "load_records_with_stats", lambda db=None, **k: (a + b, ab.ds.LoadStats(loaded=len(a + b), kept=len(a + b))))

        res = ab.run()
        assert set(res["method_sizes"]) == {"적격심사제", "소액수의견적"}
        for entry in res["arms"].values():
            assert set(entry["by_method"]) == {"적격심사제", "소액수의견적"}

    def test_small_method_is_omitted(self, monkeypatch):
        """표본이 작은 방법은 비율이 요동쳐 오해를 부르므로 빼되, 집계에는 남는다."""
        big = [_rec(f"A{i}", method="적격심사제") for i in range(ab.MIN_METHOD_N)]
        tiny = [_rec("T1", method="수의시담")]
        monkeypatch.setattr(ab.ds, "load_records_with_stats", lambda db=None, **k: (big + tiny, ab.ds.LoadStats(loaded=len(big + tiny), kept=len(big + tiny))))

        res = ab.run()
        assert "수의시담" not in res["method_sizes"]
        assert res["n_records"] == ab.MIN_METHOD_N + 1

    def test_overall_caveat_warns_about_mixing(self, monkeypatch):
        recs = [_rec(f"A{i}") for i in range(40)]
        monkeypatch.setattr(ab.ds, "load_records_with_stats", lambda db=None, **k: (recs, ab.ds.LoadStats(loaded=len(recs), kept=len(recs))))
        res = ab.run()
        assert any("입찰방법" in c for c in res["caveats"])


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


class TestExcludedCountSurvivesLoadRecordsFilter:
    """회귀(#122 사후 리뷰): 필터가 load_records 안으로 들어가면서 호출자의
    `excluded = len(loaded) - len(records)` 가 구조적으로 0 이 됐다.
    스텁이 아니라 **진짜 load_records 경로**로 오염 행이 세어지는지 본다."""

    def _seed(self, db_session, n_clean=3, n_taint=2):
        from datetime import datetime
        from app.db import models
        rows = []
        for i in range(n_clean):
            rows.append(models.OpeningResult(
                bid_no=f"AB-CLEAN-{i}", organization="o", bid_method="적격심사제",
                open_date=datetime(2026, 6, 2), basic_price=1e8, reserved_price=1.001e8,
                winner_price=0.9e8, winner_rate=90.0, lower_limit_rate=87.745,
            ))
        for i in range(n_taint):
            rows.append(models.OpeningResult(
                bid_no=f"AB-TAINT-{i}", organization="o", bid_method="적격심사제",
                open_date=datetime(2026, 6, 2), basic_price=1e8, reserved_price=1.10e8,
                winner_price=0.9e8, winner_rate=90.0, lower_limit_rate=87.745,
            ))
        db_session.add_all(rows)
        db_session.flush()   # commit 금지 — 세션 sqlite 에 남아 뒤 테스트로 샌다

    def test_arm_backtest_reports_real_exclusions(self, db_session, monkeypatch, tmp_path):
        # 정적 원장을 비워 DB 행만 보이게 (테스트 결정성)
        empty = tmp_path / "nodata"; empty.mkdir()
        # arm_backtest.run 은 data_dir 인자가 없으므로 ds.load_records_with_stats 의 기본 data_dir 만 바꾼다
        real = ab.ds.load_records_with_stats
        monkeypatch.setattr(ab.ds, "load_records_with_stats", lambda *a, **k: real(*a, **{**k, "data_dir": empty}))
        self._seed(db_session, n_clean=3, n_taint=2)
        res = ab.run(db=db_session)
        assert res["n_records"] == 3
        assert res["n_excluded_base_mismatch"] == 2, res
        assert any("2" in c and "제외" in c for c in res.get("caveats", [])), res.get("caveats")

    def test_load_records_with_stats_exposes_exclusions(self, db_session, monkeypatch, tmp_path):
        from app.services.autocalibrate import dataset as ds_mod
        empty = tmp_path / "nodata"; empty.mkdir()
        self._seed(db_session, n_clean=3, n_taint=2)
        kept, stats = ds_mod.load_records_with_stats(data_dir=empty, db=db_session)
        assert len(kept) == 3
        assert stats.excluded_base_inconsistent == 2
        assert stats.loaded == 5
        assert stats.db_contributed == 5   # DB 기여 건수가 남는다 (0건 판정용)
