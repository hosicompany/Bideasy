from app.services.bid_route import (
    BidRoute,
    classify_bid_route,
    normalize_bid_method,
    supports_smart_bid,
)


def test_normalize_bid_method_removes_g2_detail_suffix():
    assert normalize_bid_method(
        "소액수의견적-소액수의견적(2인 이상 견적 제출)"
    ) == "소액수의견적"


def test_route_classification_is_explicit():
    assert classify_bid_route("적격심사제") is BidRoute.QUALIFICATION
    assert classify_bid_route("최저가낙찰제") is BidRoute.PRICE_DOMINANT
    assert classify_bid_route("협상에의한계약") is BidRoute.NEGOTIATION
    assert classify_bid_route("종합심사낙찰제") is BidRoute.COMPREHENSIVE
    assert classify_bid_route(None) is BidRoute.UNSUPPORTED
    assert classify_bid_route("알 수 없는 방식") is BidRoute.UNSUPPORTED


def test_contract_method_is_only_a_classification_fallback():
    assert classify_bid_route(None, "협상에 의한 계약") is BidRoute.NEGOTIATION
    assert supports_smart_bid("construction", None) is False


def test_smart_bid_support_is_narrower_than_price_route():
    assert supports_smart_bid("construction", "적격심사제") is True
    assert supports_smart_bid("construction", "소액수의견적") is True
    assert supports_smart_bid("construction", "최저가낙찰제") is False
    assert supports_smart_bid("goods", "적격심사제") is False
