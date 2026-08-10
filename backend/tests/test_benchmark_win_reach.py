"""2026 G2 재판정 실행 경로의 안전성·게이트 회귀 테스트."""

import pytest

from app.services.autocalibrate.dataset import BidRecord
from scripts import benchmark_win_reach as bwr


def _frontier(ci_lower=30.0, oracle_rate=35.0):
    return {
        "holdout_oracle": {"win_rate": oracle_rate},
        "points": [
            {"dropout_cap_pp": 10.0, "holdout_win_ci95": [ci_lower, 36.0]},
        ],
    }


def _record(bid_no, reserved):
    return BidRecord(
        bid_no=bid_no,
        title="",
        org="",
        bid_method="적격심사제",
        basic_price=100_000_000,
        estimated_price=100_000_000,
        reserved_price=reserved,
        winner_price=90_000_000,
        winner_rate=90.0,
        lower_limit_rate=89.745,
        year=2026,
    )


class TestG2Evaluation:
    def test_waits_until_400_clean_holdout_records(self):
        result = bwr.evaluate_g2(_frontier(ci_lower=30.0), holdout_n=399)

        assert result["condition_met"] is True
        assert result["sample_requirement_met"] is False
        assert result["status"] == "NOT_READY"

    def test_passes_on_wilson_lower_bound(self):
        result = bwr.evaluate_g2(_frontier(ci_lower=30.0), holdout_n=400)

        assert result["target_pct"] == 28.0
        assert result["status"] == "PASS"

    def test_fails_when_wilson_lower_bound_misses_target(self):
        result = bwr.evaluate_g2(_frontier(ci_lower=27.9), holdout_n=400)

        assert result["condition_met"] is False
        assert result["status"] == "FAIL"


class TestG2RunSafety:
    def test_2026_default_output_is_isolated_from_live_arm_params(self):
        path, canonical = bwr.result_path_for_run(
            None, include_db=True, holdout_years=(2026,), bid_method=None,
        )

        assert canonical is False
        assert path.name == "benchmark_g2_2026_db_results.json"
        assert path.resolve() != bwr.RESULTS_PATH.resolve()

    def test_quick_run_is_also_isolated(self):
        path, canonical = bwr.result_path_for_run(
            None, include_db=False, holdout_years=(2025,), bid_method=None,
            quick=True,
        )

        assert canonical is False
        assert path.name == "benchmark_quick_2025_static_results.json"

    def test_noncanonical_sources_and_methods_use_distinct_paths(self):
        configs = [
            (True, None),
            (False, None),
            (True, "적격심사제"),
            (True, "소액수의견적"),
        ]

        paths = {
            bwr.result_path_for_run(
                None,
                include_db=include_db,
                holdout_years=(2026,),
                bid_method=bid_method,
            )[0].name
            for include_db, bid_method in configs
        }

        assert paths == {
            "benchmark_g2_2026_db_results.json",
            "benchmark_g2_2026_static_results.json",
            "benchmark_g2_2026_db_qualification_results.json",
            "benchmark_g2_2026_db_small_quote_results.json",
        }

    def test_noncanonical_run_cannot_overwrite_live_arm_params(self):
        with pytest.raises(ValueError, match="다른 --json-out"):
            bwr.result_path_for_run(
                str(bwr.RESULTS_PATH), include_db=True,
                holdout_years=(2026,), bid_method=None,
            )

    def test_load_excludes_known_price_basis_mismatch(self, monkeypatch):
        monkeypatch.setattr(
            bwr.ds,
            "load_records",
            lambda db=None, strict_db=False: [
                _record("VALID", 100_000_000),
                _record("MISMATCH", 110_000_000),
            ],
        )

        raw, deduped, duplicates, excluded = bwr.load_all()

        assert [r.bid_no for r in raw] == ["VALID"]
        assert [r.bid_no for r in deduped] == ["VALID"]
        assert duplicates == 0
        assert excluded == 1

    def test_include_db_propagates_database_failure(self, monkeypatch):
        class BrokenDB:
            def query(self, *args, **kwargs):
                raise RuntimeError("simulated database failure")

            def close(self):
                pass

        monkeypatch.setattr(
            "app.db.session.SessionLocal",
            lambda: BrokenDB(),
        )

        with pytest.raises(RuntimeError, match="simulated database failure"):
            bwr.load_all(include_db=True)
