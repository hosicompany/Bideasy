"""Tests for bid_verifier service."""

import pytest

import app.services.bid_verifier as bv_mod
import app.services.organization_insights as oi_mod


@pytest.fixture(autouse=True)
def _patch_db(historical_test_db, monkeypatch):
    """Patch DB_PATH for both verifier and insights (tip generation calls insights)."""
    monkeypatch.setattr(bv_mod, "DB_PATH", historical_test_db)
    monkeypatch.setattr(oi_mod, "DB_PATH", historical_test_db)
    oi_mod.clear_cache()


# ── Integration tests (verify_bid full flow) ─────────────────

def test_verify_found(historical_test_db):
    result = bv_mod.verify_bid("BID001", 89000000, 100000000)
    assert result["found"] is True
    assert result["my_rate"] == 89.0
    assert result["winning_rate"] == 88.50
    assert result["gap"] == 0.5
    assert result["winning_price"] == 88500000
    assert result["winner_name"] == "업체A"
    assert result["total_participants"] == 15
    assert isinstance(result["analysis"], str)
    assert isinstance(result["tip"], str)


def test_verify_not_found(historical_test_db):
    result = bv_mod.verify_bid("NONEXISTENT99", 89000000, 100000000)
    assert result["found"] is False
    assert "찾을 수 없습니다" in result["message"]


def test_verify_zero_basic_price(historical_test_db):
    result = bv_mod.verify_bid("BID001", 89000000, 0)
    assert result == {"error": "기초금액이 0 이하입니다."}


def test_verify_exact_match(historical_test_db):
    # my_bid_price == winning_price → gap should be 0
    result = bv_mod.verify_bid("BID001", 88500000, 100000000)
    assert result["found"] is True
    assert result["gap"] == 0.0


def test_verify_close_miss(historical_test_db):
    # BID001 winning_rate=88.50, my_price=88300000 → my_rate=88.3, gap=-0.2
    result = bv_mod.verify_bid("BID001", 88300000, 100000000)
    assert result["found"] is True
    assert abs(result["gap"]) < 0.3
    assert "아쉽게 놓치셨어요" in result["analysis"]


def test_verify_large_gap_above(historical_test_db):
    # my_price=95M → my_rate=95.0, gap=+6.5
    result = bv_mod.verify_bid("BID001", 95000000, 100000000)
    assert result["found"] is True
    assert "높게" in result["analysis"]


def test_verify_large_gap_below(historical_test_db):
    # my_price=80M → my_rate=80.0, gap=-8.5
    result = bv_mod.verify_bid("BID001", 80000000, 100000000)
    assert result["found"] is True
    assert "낮게" in result["analysis"]


def test_verify_with_organization(historical_test_db):
    result = bv_mod.verify_bid("BID001", 89000000, 100000000, organization="서울시청")
    assert "서울시청" in result["tip"]


def test_verify_empty_organization(historical_test_db):
    # empty org falls back to historical org ("서울시청") via `or` logic
    result = bv_mod.verify_bid("BID001", 89000000, 100000000, organization="")
    assert "서울시청" in result["tip"]


# ── Unit tests: _estimate_rank ───────────────────────────────

def test_estimate_rank_exact():
    assert bv_mod._estimate_rank(88.00, 88.005, 20) == 1


def test_estimate_rank_no_participants():
    assert bv_mod._estimate_rank(88.00, 87.00, None) is None


def test_estimate_rank_moderate_gap():
    # gap=0.4, participants=20 → bracket [0.3, 0.5) → max(3, int(20 * 0.3)) = 6
    assert bv_mod._estimate_rank(88.40, 88.00, 20) == 6


# ── Unit tests: _generate_analysis ───────────────────────────

def test_generate_analysis_near_miss():
    text = bv_mod._generate_analysis(88.02, 88.00, 0.02, 2, 20)
    assert "근접" in text


def test_generate_analysis_with_rank():
    text = bv_mod._generate_analysis(88.10, 88.00, 0.10, 2, 50)
    assert "상위권" in text


# ── Unit tests: _generate_tip ────────────────────────────────

def test_generate_tip_no_org():
    text = bv_mod._generate_tip("")
    assert "과거 낙찰 패턴" in text
