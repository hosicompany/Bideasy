"""공고의 낙찰자 결정 방식을 제품 지원 route 로 분류하는 단일 소스.

이 모듈은 가격 계산을 하지 않는다. 원문 입찰방법을 보존한 채 정규화하고,
Smart Bid 같은 소비자가 지원 여부를 명시적으로 판단할 수 있게 한다.
알 수 없는 방식을 가격경쟁 ``DEFAULT`` 로 추정하지 않는 것이 핵심 불변식이다.
"""

from __future__ import annotations

from app.schemas.algorithm_evidence import BidRoute


SMART_BID_SUPPORTED_METHODS = frozenset({"적격심사제", "소액수의견적"})


def normalize_bid_method(raw: str | None) -> str | None:
    """조달청 상세 설명이 붙은 입찰방법을 비교 가능한 첫 토큰으로 정규화한다."""
    if not raw or not raw.strip():
        return None

    compact = " ".join(raw.strip().split())
    aliases = (
        "적격심사제",
        "소액수의견적",
        "제한적최저가(낙찰하한율)",
        "최저가낙찰제",
        "협상에의한계약",
        "종합평가낙찰제",
        "종합심사낙찰제",
    )
    for canonical in aliases:
        if compact.startswith(canonical):
            return canonical

    # 조달청 원문은 보통 "방법-상세 설명" 형태다. 알 수 없는 값도 첫 토큰을
    # 돌려줘야 응답 evidence 에서 원문을 숨기지 않고 UNSUPPORTED 로 판정할 수 있다.
    return compact.split("-", 1)[0].strip() or None


def classify_bid_route(
    bid_method: str | None,
    contract_method: str | None = None,
) -> BidRoute:
    """입찰방법/계약방법을 제품 route 로 분류한다.

    ``contract_method`` 는 ``bid_method`` 가 비어 있거나 상위 분류만 담긴 오래된
    공고를 위한 보조 정보다. 어느 쪽도 가격경쟁임을 입증하지 못하면 UNSUPPORTED다.
    """
    method = normalize_bid_method(bid_method)
    combined = " ".join(part for part in (method, contract_method) if part).lower()
    if not combined:
        return BidRoute.UNSUPPORTED

    if "협상" in combined:
        return BidRoute.NEGOTIATION
    if any(token in combined for token in ("종합평가", "종합심사", "기술제안")):
        return BidRoute.COMPREHENSIVE
    if method == "적격심사제" or "적격심사" in combined:
        return BidRoute.QUALIFICATION
    if method in {
        "소액수의견적",
        "제한적최저가(낙찰하한율)",
        "최저가낙찰제",
    }:
        return BidRoute.PRICE_DOMINANT
    return BidRoute.UNSUPPORTED


def supports_smart_bid(bid_type: str | None, bid_method: str | None) -> bool:
    """현재 검증 범위인 공사 적격심사/소액수의견적만 허용한다."""
    return (
        (bid_type or "").strip().lower() == "construction"
        and normalize_bid_method(bid_method) in SMART_BID_SUPPORTED_METHODS
    )
