"""공고 컨텍스트가 확인된 기초금액·공고 하한율을 주고, 상세 계산이 공고 하한율을 따르는지."""
from app.db import models


def test_context_returns_confirmed_basis_not_estimated(client, db_session):
    db_session.add(models.Notice(bid_no="CTX-BASIS-1", title="t", basic_price=950_000_000,
                                 basis_amount=1_045_000_000, lower_limit_rate=89.745,
                                 contract_type="CONSTRUCTION"))
    db_session.add(models.Notice(bid_no="CTX-BASIS-2", title="t", basic_price=950_000_000,
                                 contract_type="CONSTRUCTION"))
    db_session.commit()
    a = client.get("/api/v1/bids/CTX-BASIS-1/context").json()
    assert a["basis_amount"] == 1_045_000_000 and a["lower_limit_rate"] == 89.745
    assert a["estimated_price"] == 950_000_000
    b = client.get("/api/v1/bids/CTX-BASIS-2/context").json()
    assert b["basis_amount"] is None  # 미확인이면 비워 둔다 — 추정가격으로 대신 채우지 않는다


def test_detailed_calc_uses_notice_rate_when_given(client):
    body = {"basic_price": 1_110_000_000, "rate": -10.8, "contract_type": "CONSTRUCTION", "a_value": 0}
    plain = client.post("/api/v1/bids/calculate/detailed", json=body).json()
    given = client.post("/api/v1/bids/calculate/detailed", json={**body, "lower_limit_rate": 87.995}).json()
    assert plain["lower_limit_price"] != given["lower_limit_price"]
    assert given["lower_limit_price"] == int(1_110_000_000 * 0.87995 // 10 * 10)
