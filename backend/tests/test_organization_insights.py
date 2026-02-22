"""Tests for organization_insights service."""

import statistics

import pytest

import app.services.organization_insights as oi_mod


@pytest.fixture(autouse=True)
def _patch_db(historical_test_db, monkeypatch):
    """Patch DB_PATH and clear LRU cache before every test."""
    monkeypatch.setattr(oi_mod, "DB_PATH", historical_test_db)
    oi_mod.clear_cache()


# ── Happy path ───────────────────────────────────────────────

def test_happy_path(historical_test_db):
    result = oi_mod.get_agency_insights("서울시청")
    assert result["found"] is True
    assert result["total_bids"] == 10
    assert result["agency_name"] == "서울시청"
    for key in ("avg_rate", "median_rate", "min_rate", "max_rate",
                "std_rate", "avg_participants", "recent_6m_count",
                "rate_trend", "diff_from_global", "insight"):
        assert key in result


def test_rates_computed_correctly(historical_test_db):
    result = oi_mod.get_agency_insights("서울시청")

    # Seed rates: 88.50, 87.90, 89.10, 88.00, 87.80, 88.20, 86.50, 87.00, 86.20, 86.80
    rates = [88.50, 87.90, 89.10, 88.00, 87.80, 88.20, 86.50, 87.00, 86.20, 86.80]
    assert result["avg_rate"] == round(statistics.mean(rates), 2)
    assert result["median_rate"] == round(statistics.median(rates), 2)
    assert result["min_rate"] == round(min(rates), 2)
    assert result["max_rate"] == round(max(rates), 2)
    assert result["std_rate"] == round(statistics.stdev(rates), 2)


# ── Matching logic ───────────────────────────────────────────

def test_partial_match(historical_test_db):
    result = oi_mod.get_agency_insights("서울")
    assert result["found"] is True
    assert result["total_bids"] == 10  # matches "서울시청" via LIKE


def test_not_found(historical_test_db):
    result = oi_mod.get_agency_insights("존재하지않는기관")
    assert result["found"] is False
    assert "데이터가 없습니다" in result["message"]


def test_bid_type_filter(historical_test_db):
    result = oi_mod.get_agency_insights("강남구청", bid_type="goods")
    assert result["found"] is True
    assert result["total_bids"] == 2


# ── Edge cases ───────────────────────────────────────────────

def test_db_not_found(monkeypatch, tmp_path):
    monkeypatch.setattr(oi_mod, "DB_PATH", tmp_path / "nonexistent.db")
    oi_mod.clear_cache()
    result = oi_mod.get_agency_insights("아무기관")
    assert result == {"error": "historical_db_not_found"}


def test_recent_6m_count(historical_test_db):
    result = oi_mod.get_agency_insights("서울시청")
    assert result["recent_6m_count"] == 6


def test_rate_trend_rising(historical_test_db):
    result = oi_mod.get_agency_insights("서울시청")
    # Recent avg ≈ 88.25, Old avg ≈ 86.63 → diff > 0.3 → rising
    assert result["rate_trend"] == "rising"


def test_participants_median(historical_test_db):
    result = oi_mod.get_agency_insights("서울시청")
    # prtcptCnum values: 15, 20, 8, 12, 5, 18, 25, 30, 10, 22
    expected = round(statistics.median([15, 20, 8, 12, 5, 18, 25, 30, 10, 22]), 1)
    assert result["avg_participants"] == expected


# ── Cache ────────────────────────────────────────────────────

def test_cache_works(historical_test_db):
    r1 = oi_mod.get_agency_insights("서울시청")
    r2 = oi_mod.get_agency_insights("서울시청")
    assert r1 is r2  # same cached object

    oi_mod.clear_cache()
    r3 = oi_mod.get_agency_insights("서울시청")
    assert r3["found"] is True  # still works after cache clear


# ── _generate_insight unit tests ─────────────────────────────

def test_insight_high_rate():
    text = oi_mod._generate_insight(90.0, 88.0, 10.0, "stable", 50)
    assert "높은 편이에요" in text


def test_insight_low_competition():
    text = oi_mod._generate_insight(88.0, 88.0, 5.0, "stable", 50)
    assert "경쟁이 비교적 적은" in text


def test_insight_few_data():
    text = oi_mod._generate_insight(88.0, 88.0, None, "stable", 3)
    assert "참고용으로만" in text
