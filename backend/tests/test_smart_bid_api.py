"""Tests for smart_bid API endpoints (agency/insights + verify)."""

import pytest

import app.services.organization_insights as oi_mod
import app.services.bid_verifier as bv_mod


@pytest.fixture(autouse=True)
def _patch_db(historical_test_db, monkeypatch):
    monkeypatch.setattr(oi_mod, "DB_PATH", historical_test_db)
    monkeypatch.setattr(bv_mod, "DB_PATH", historical_test_db)
    oi_mod.clear_cache()


# ── GET /agency/insights ─────────────────────────────────────

def test_insights_endpoint_200(client):
    resp = client.get(
        "/api/v1/smart-bid/agency/insights",
        params={"agency_name": "서울시청"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["found"] is True
    assert data["total_bids"] == 10


def test_insights_endpoint_not_found(client):
    resp = client.get(
        "/api/v1/smart-bid/agency/insights",
        params={"agency_name": "미존재기관"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["found"] is False


def test_insights_endpoint_missing_param(client):
    resp = client.get("/api/v1/smart-bid/agency/insights")
    assert resp.status_code == 422


# ── POST /verify ─────────────────────────────────────────────

def test_verify_endpoint_200(client):
    resp = client.post("/api/v1/smart-bid/verify", json={
        "bid_no": "BID001",
        "my_bid_price": 89000000,
        "basic_price": 100000000,
    })
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["found"] is True
    assert data["my_rate"] == 89.0


def test_verify_endpoint_zero_basic(client):
    resp = client.post("/api/v1/smart-bid/verify", json={
        "bid_no": "BID001",
        "my_bid_price": 89000000,
        "basic_price": 0,
    })
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "error" in data
