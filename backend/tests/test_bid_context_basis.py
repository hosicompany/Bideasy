"""Public context and static calculator must preserve price-basis semantics."""

from datetime import datetime
from pathlib import Path

from app.db import models


def _seed_notice(db_session, bid_no: str, *, basis_amount: float | None) -> None:
    notice = models.Notice(
        bid_no=bid_no,
        title="가격 기준 회귀 테스트",
        basic_price=100_000_000.0,  # presmptPrce: estimate, never a basis fallback
        basis_amount=basis_amount,
        contract_type="CONSTRUCTION",
        bid_method="적격심사제",
    )
    db_session.add(notice)
    db_session.commit()


def test_context_keeps_estimate_separate_when_basis_is_missing(client, db_session):
    _seed_notice(db_session, "CTX-UNCONFIRMED-000", basis_amount=None)

    response = client.get("/api/v1/bids/CTX-UNCONFIRMED-000/context")

    assert response.status_code == 200
    body = response.json()
    assert body["estimated_price"] == 100_000_000.0
    assert body["basis_amount"] is None
    assert body["basis_status"] == "unconfirmed"
    assert body["lower_limit_rate"] is None


def test_context_returns_confirmed_basis_and_versioned_construction_rate(client, db_session):
    _seed_notice(db_session, "CTX-CONFIRMED-000", basis_amount=110_000_000.0)

    response = client.get("/api/v1/bids/CTX-CONFIRMED-000/context")

    assert response.status_code == 200
    body = response.json()
    assert body["estimated_price"] == 100_000_000.0
    assert body["basis_amount"] == 110_000_000.0
    assert body["basis_status"] == "confirmed"
    assert body["lower_limit_rate"] == 89.745
    assert body["lower_limit_source"] == "table"


def test_context_exposes_rule_date_for_historical_construction(client, db_session):
    notice = models.Notice(
        bid_no="CTX-HISTORICAL-000",
        title="과거 규칙 재현",
        basic_price=90_000_000,
        basis_amount=100_000_000,
        contract_type="CONSTRUCTION",
        start_date=datetime(2025, 12, 31),
        a_value_applicable="N",
    )
    db_session.add(notice)
    db_session.commit()

    response = client.get("/api/v1/bids/CTX-HISTORICAL-000/context")

    assert response.status_code == 200
    body = response.json()
    assert body["bid_date"] == "2025-12-31"
    assert body["lower_limit_rate"] == 87.745
    assert body["lower_limit_source"] == "table"


def test_static_calculator_never_assigns_estimated_price_to_basis():
    calculator = (
        Path(__file__).resolve().parents[2]
        / "infra"
        / "nginx"
        / "html"
        / "calculator.html"
    ).read_text(encoding="utf-8")

    assert "st.basic = ctx.estimated_price" not in calculator
    assert "ctx.basis_status === 'confirmed'" in calculator
    assert "추정가격은 자동 입력하지 않았습니다" in calculator


def test_static_calculator_does_not_use_universal_service_goods_rate():
    calculator = (
        Path(__file__).resolve().parents[2]
        / "infra"
        / "nginx"
        / "html"
        / "calculator.html"
    ).read_text(encoding="utf-8")

    assert "SERVICE: 87.995" not in calculator
    assert "GOODS: 87.995" not in calculator
    assert "공고별 낙찰하한율을 확인하지 못해" in calculator


def test_api_context_cache_preserves_contract_formula_fields(
    client, db_session, monkeypatch
):
    """최초 OpenAPI 응답과 다음 DB cache 응답의 계산 입력이 같아야 한다."""
    from app.services.bid_detail import BidDetailService

    detail = {
        "bid_no": "R26CACHE0001-000",
        "title": "컨텍스트 캐시 공식 parity",
        "estimated_price": "90000000",
        "budget_amount": "110000000",
        "organization": "A기관",
        "demand_organization": "B기관",
        "contract_method": "일반경쟁",
        "bid_method": "적격심사제",
        "opening_date": "2026-09-01 11:00",
        "contract_type": "SERVICE",
        "raw_data": {
            "presmptPrce": "90000000",
            "bssAmt": "100000000",
            "sucsfbidLwltRate": "92.6",
            "rsrvtnPrceRngBgnRate": "-2",
            "rsrvtnPrceRngEndRate": "2",
            "bidPrceCalclA": "7654321",
            "bidPrceCalclAYn": "Y",
            "purcnstcst": "80000000",
        },
    }
    monkeypatch.setattr(
        BidDetailService,
        "fetch_bid_detail_robust",
        staticmethod(lambda *_args, **_kwargs: detail),
    )

    first = client.get("/api/v1/bids/R26CACHE0001-000/context")
    second = client.get("/api/v1/bids/R26CACHE0001-000/context")

    assert first.status_code == second.status_code == 200
    first_body = first.json()
    second_body = second.json()
    assert first_body["source"] == "api"
    assert second_body["source"] == "cache"
    for field in (
        "estimated_price",
        "basis_amount",
        "basis_status",
        "budget_amount",
        "contract_type",
        "lower_limit_rate",
        "prdprc_range_bgn",
        "prdprc_range_end",
        "a_value",
        "a_value_source",
        "a_value_applicable",
        "net_cost",
    ):
        assert second_body[field] == first_body[field], field


def test_explicit_notice_ordinal_never_falls_back_to_another_revision(
    client, db_session, monkeypatch
):
    _seed_notice(db_session, "R26REVISION0001-000", basis_amount=100_000_000)
    monkeypatch.setattr(
        "app.services.bid_detail.BidDetailService.fetch_bid_detail_robust",
        lambda *_args, **_kwargs: None,
    )

    response = client.get("/api/v1/bids/R26REVISION0001-001/context")

    assert response.status_code == 200
    assert response.json()["found"] is False


def test_direct_search_rejects_wrong_api_ordinal(monkeypatch):
    from app.services.bid_detail import BidDetailService

    class Response:
        status_code = 200

        @staticmethod
        def json():
            return {
                "response": {
                    "body": {
                        "items": [
                            {
                                "bidNtceNo": "R26REVISION0002",
                                "bidNtceOrd": "000",
                                "bidNtceNm": "이전 차수",
                            }
                        ]
                    }
                }
            }

    monkeypatch.setattr(
        "app.services.bid_detail.requests.get",
        lambda *_args, **_kwargs: Response(),
    )

    assert (
        BidDetailService._fetch_by_bidno_search("R26REVISION0002", "001")
        is None
    )
