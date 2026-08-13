"""Legacy replay must abstain on unknown inputs and stay out of verified metrics."""

from datetime import datetime

from app.db import models
from app.services.calculator import CalculatorService
from app.services.prediction_verifier import (
    compute_recommendations,
    evaluate_against_actual,
    verify_notices,
)


def _notice(**overrides):
    values = {
        "bid_no": "REPLAY-1",
        "title": "사후 재생 계약 테스트",
        "basic_price": 90_000_000,  # 추정가격 — 계산에 쓰면 안 됨
        "basis_amount": 100_000_000,
        "contract_type": "CONSTRUCTION",
        "bid_method": "적격심사제",
        "contract_method": "일반경쟁",
        "lower_limit_rate": 89.745,
        "a_value": 7_654_321,
        "a_value_source": "tier0",
        "a_value_applicable": "Y",
        "start_date": datetime(2026, 6, 1),
    }
    values.update(overrides)
    return models.Notice(**values)


def _opening(**overrides):
    values = {
        "bid_no": "REPLAY-1",
        "basic_price": 100_000_000,
        "reserved_price": 100_500_000,
        "winner_price": 91_000_000,
        "winner_rate": 90.547,
        "lower_limit_rate": 89.745,
        "participants_count": 10,
    }
    values.update(overrides)
    return models.OpeningResult(**values)


def test_replay_never_uses_estimated_price_as_basis():
    assert compute_recommendations(_notice(basis_amount=None)) == {}


def test_replay_abstains_when_a_value_status_is_unknown():
    assert compute_recommendations(
        _notice(a_value=0, a_value_source=None, a_value_applicable=None)
    ) == {}


def test_replay_uses_a_value_and_explicit_notice_rate(monkeypatch):
    captured = {}

    def fake_recommend(**kwargs):
        captured.update(kwargs)
        return {
            "recommended_price": 90_000_000,
            "bid_rate": 90.0,
            "adjustment": 0.0,
            "margin": 0.255,
        }

    monkeypatch.setattr(CalculatorService, "recommend_bid_price", fake_recommend)
    notice = _notice()

    recommendations = compute_recommendations(notice)

    assert recommendations["standard"]["price"] == (
        CalculatorService.calculate_safe_bid(
            100_000_000, -2.5, notice.a_value
        )
    )
    assert captured["basic_price"] == 100_000_000
    assert captured["a_value"] == 7_654_321
    assert captured["lower_limit_rate"] == 89.745


def test_post_opening_replay_is_never_verified(monkeypatch, db_session):
    notice = _notice()
    opening = _opening()
    db_session.add_all([notice, opening])
    db_session.flush()
    monkeypatch.setattr(
        CalculatorService,
        "recommend_bid_price",
        lambda **_kwargs: {
            "recommended_price": 90_000_000,
            "bid_rate": 90.0,
            "adjustment": 0.0,
            "margin": 0.255,
        },
    )

    result = evaluate_against_actual(notice, opening)
    summary = verify_notices(db_session, [notice])

    assert result is not None
    assert result["status"] == "COUNTERFACTUAL"
    assert result["evidence_kind"] == "post_opening_current_strategy_replay"
    assert summary["verified"] == 0
    assert summary["counterfactual"] == 1
