"""기초금액 판정 단일 소스.

왜 있나
-------
`Notice.basic_price` 는 `presmptPrce`(추정가격, 부가세 제외)다. 기초금액이
아니다. 기초금액은 전용 오퍼레이션이 주는 값으로 `Notice.basis_amount` 에만
들어간다(커버리지 실측 80%). 경위: docs/PRICE_BASE_DEFECT.md

호출부가 각자 "basis_amount 가 있으면 쓰고 없으면 basic_price" 식으로 판단하면
언젠가 한쪽이 폴백을 되살려 **틀린 기초금액으로 '안전'이라고 말하게 된다.**
그게 이번 사고다. 판정을 여기 한 곳에 고정한다.

계약 두 가지
-----------
1. **추정하지 않는다** — 기초금액이 없으면 `None`. `basic_price × 1.1` 같은
   보정 금지(실측 비율이 0.9877~1.1223 로 흩어진다).
2. **없으면 안전 판정을 보류한다** — 하한선을 못 구하니 "안전"도 "위험"도
   말할 수 없다. 모르는 것을 모른다고 말하는 편이 낫다.
"""
from __future__ import annotations

from app.core.config import settings
from app.services.bid_data_quality import base_is_consistent

# 판정 결과
CONFIRMED = "confirmed"      # 기초금액 확인됨 — 정상 계산
UNCONFIRMED = "unconfirmed"  # 기초금액 미확인 — 안전 판정 보류
LEGACY = "legacy"            # 시행 전(플래그 OFF) — 기존 동작 유지


def enforcing() -> bool:
    """기초금액 시행 여부.

    수집(B-1)을 먼저 배포하고 소비(B-2)는 커버리지가 쌓인 뒤 켠다. 켜기 전에
    배포해도 동작이 바뀌지 않도록 기본 OFF 다.
    """
    return bool(getattr(settings, "BASIS_AMOUNT_ENFORCE", False))


def _basis_from_opening(opening) -> float | None:
    """개찰결과에서 얻는 기초금액. 기준이 어긋난 행은 쓰지 않는다.

    개찰 API 는 `bssAmt`(기초금액)를 주므로 **개찰이 끝나면 기초금액을 안다.**
    공고 단계에서 못 구한 건도 여기서 확정된다(실측: 마감 공고 4,343건이
    이 경로로 '미확인'에서 벗어난다).
    """
    if opening is None:
        return None
    bp = float(getattr(opening, "basic_price", 0) or 0)
    rp = float(getattr(opening, "reserved_price", 0) or 0)
    if bp <= 0:
        return None
    # 예정가격이 있으면 사정률로 기준 일치를 검증한다(백필 안 된 옛 행 배제)
    if rp > 0 and not base_is_consistent(bp, rp):
        return None
    return bp


def basis_status(notice, opening=None) -> str:
    """이 공고의 기초금액 상태."""
    if not enforcing():
        return LEGACY
    if _basis_from_opening(opening) is not None:
        return CONFIRMED
    if notice is not None and (getattr(notice, "basis_amount", None) or 0) > 0:
        return CONFIRMED
    return UNCONFIRMED


def confirmed_basis(notice, opening=None) -> float | None:
    """계산에 써도 되는 기초금액. 확인 안 됐으면 None — 추정하지 않는다.

    개찰결과가 있으면 그쪽을 먼저 본다. 개찰 시점의 실값이라 가장 확실하다.
    """
    from_opening = _basis_from_opening(opening)
    if from_opening is not None:
        return from_opening
    if notice is None:
        return None
    if not enforcing():
        # 시행 전에는 기존 동작 유지(추정가격을 그대로 쓴다). 정확하진 않지만
        # 이 값으로 계속 돌아온 화면이라, 켜기 전까지 갑자기 바꾸지 않는다.
        return float(getattr(notice, "basic_price", 0) or 0) or None
    v = getattr(notice, "basis_amount", None) or 0
    return float(v) if v > 0 else None


def display_basis(notice, opening=None) -> tuple[int, str]:
    """화면 표기용 (금액, 상태). 미확인이면 금액 0 — 틀린 숫자를 보여주지 않는다."""
    st = basis_status(notice, opening)
    if st == UNCONFIRMED:
        return 0, st
    return int(confirmed_basis(notice, opening) or 0), st
