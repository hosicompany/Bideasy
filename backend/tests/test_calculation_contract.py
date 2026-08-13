"""Cross-channel calculation contract regression tests."""

from datetime import date
from pathlib import Path

import pytest

from app.services.calculator import CalculatorService


def test_simple_and_detailed_endpoints_share_a_value_formula(client):
    payload = {
        "basic_price": 100_000_000,
        "rate": -5.1234,
        "contract_type": "CONSTRUCTION",
        "a_value": 7_654_321,
        "a_value_status": "confirmed",
        "lower_limit_rate": 89.745,
        "prdprc_range_bgn": -2,
        "prdprc_range_end": 2,
    }

    simple = client.post("/api/v1/bids/calculate", json=payload)
    detailed = client.post("/api/v1/bids/calculate/detailed", json=payload)

    assert simple.status_code == detailed.status_code == 200
    assert simple.json()["result_price"] == detailed.json()["result_price"]
    assert simple.json()["is_safe"] == (
        detailed.json()["safety_level"] != "DANGER"
    )
    assert detailed.json()["result_price"] % 10 == 0


@pytest.mark.parametrize("contract_type", ["SERVICE", "GOODS"])
def test_non_construction_without_notice_rate_fails_closed(client, contract_type):
    response = client.post(
        "/api/v1/bids/calculate/detailed",
        json={
            "basic_price": 100_000_000,
            "rate": -5,
            "contract_type": contract_type,
            "a_value_status": "not_applicable",
        },
    )

    assert response.status_code == 400
    assert "공고가 명시한 낙찰하한율" in response.json()["detail"]


def test_notice_lower_rate_overrides_contract_default(client):
    response = client.post(
        "/api/v1/bids/calculate/detailed",
        json={
            "basic_price": 100_000_000,
            "rate": -10,
            "contract_type": "SERVICE",
            "a_value_status": "not_applicable",
            "lower_limit_rate": 88.2,
        },
    )

    assert response.status_code == 200
    assert response.json()["lower_limit_rate"] == 88.2
    assert response.json()["lower_limit_price"] == 88_200_000


def test_unknown_planned_price_range_is_not_invented(client):
    response = client.post(
        "/api/v1/bids/calculate/detailed",
        json={
            "basic_price": 100_000_000,
            "rate": -5,
            "contract_type": "CONSTRUCTION",
            "a_value_status": "not_applicable",
        },
    )

    assert response.status_code == 200
    assert response.json()["estimated_price_min"] is None
    assert response.json()["estimated_price_max"] is None


@pytest.mark.parametrize(
    ("a_value", "a_value_status"),
    [
        (0, None),
        (0, "confirmed"),
        (1_000, "not_applicable"),
    ],
)
def test_calculation_requires_consistent_a_value_status(
    client, a_value, a_value_status
):
    payload = {
        "basic_price": 100_000_000,
        "rate": -5,
        "contract_type": "CONSTRUCTION",
        "a_value": a_value,
    }
    if a_value_status is not None:
        payload["a_value_status"] = a_value_status

    response = client.post("/api/v1/bids/calculate/detailed", json=payload)

    if a_value == 0 and a_value_status is None:
        # Existing manual-calculator clients remain compatible. Notice-backed
        # channels send an explicit provenance status and fail closed upstream.
        assert response.status_code == 200
    else:
        assert response.status_code == 422


def test_strategy_formula_decimal_boundary_matches_production():
    from app.services.calculator import CalculatorService

    price = CalculatorService.calculate_strategy_price(
        526_205_133_281,
        0.6,
        88.045,
        19_242_375_200,
    )

    assert price == 468_377_519_400


def test_zero_notice_lower_rate_is_rejected(client):
    response = client.post(
        "/api/v1/bids/calculate/detailed",
        json={
            "basic_price": 100_000_000,
            "rate": -5,
            "contract_type": "GOODS",
            "a_value": 0,
            "a_value_status": "not_applicable",
            "lower_limit_rate": 0,
        },
    )

    assert response.status_code == 422


def test_explicit_range_and_historical_rule_are_reproduced():
    result = CalculatorService.calculate_detailed_bid(
        basic_price=100_000_000,
        rate=-10,
        contract_type="CONSTRUCTION",
        bid_date=date(2025, 12, 31),
        prdprc_range_bgn=-2,
        prdprc_range_end=2,
    )

    assert result.lower_limit_rate == 87.745
    assert result.estimated_price_min == 98_000_000
    assert result.estimated_price_max == 102_000_000


@pytest.mark.parametrize("a_value", [-1, 100_000_000, 100_000_001])
def test_invalid_a_value_cannot_produce_a_price(a_value):
    with pytest.raises(ValueError, match="A값"):
        CalculatorService.calculate_detailed_bid(
            basic_price=100_000_000,
            rate=-5,
            a_value=a_value,
        )


def test_static_calculator_requires_a_provenance_and_revalidates_before_copy():
    html = (
        Path(__file__).parents[2] / "infra/nginx/html/calculator.html"
    ).read_text(encoding="utf-8")

    assert 'id="aval-na"' in html
    assert "A값 산정 비대상임을 확인했습니다" in html
    assert "A값은 0 이상이며 확정 기초금액보다 작아야 합니다" in html
    assert "fetch(API_BASE + '/bids/calculate/detailed'" in html
    assert "serverPrice % 10 !== 0" in html
    assert "st.explicitLower = null" in html
    assert "서버 확인 후 복사" in html
