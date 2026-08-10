"""입찰 성능 집계의 금액 기준 일관성 판정 단일 소스.

예정가격(`reserved_price`)은 기초금액 주변에서 정해지므로 두 값의 비율이
구조적으로 1.0 부근이어야 한다. 과거 `basic_price` 에 추정가격(부가세 제외)이
저장된 행은 이 비율이 약 1.10으로 나타난다. 이런 행을 전략 성능에 섞으면
무효율이 전략 문제가 아니라 데이터 기준 차이로 급등한다.

원장은 삭제하거나 고치지 않는다. 집계 시 유효/불일치/판정불가로 분리하고
제외 건수를 반드시 함께 보고한다.
"""

from __future__ import annotations

from typing import Literal


# 정적 개찰 4,854건 실측 범위 0.978~1.022의 약 두 배 여유를 두되,
# 추정가격 혼입 신호인 1.10은 확실히 제외한다.
BASE_RATIO_MIN = 0.94
BASE_RATIO_MAX = 1.06

BaseConsistency = Literal["valid", "mismatch", "unknown"]


def classify_base_consistency(
    basic_price: float | int | None,
    reserved_price: float | int | None,
) -> BaseConsistency:
    """기초금액과 예정가격이 같은 기준인지 세 상태로 분류한다."""
    if not basic_price or not reserved_price:
        return "unknown"
    if basic_price <= 0 or reserved_price <= 0:
        return "unknown"
    ratio = float(reserved_price) / float(basic_price)
    if BASE_RATIO_MIN <= ratio <= BASE_RATIO_MAX:
        return "valid"
    return "mismatch"


def base_is_consistent(
    basic_price: float | int | None,
    reserved_price: float | int | None,
) -> bool:
    """집계 포함 여부의 bool 편의 함수."""
    return classify_base_consistency(basic_price, reserved_price) == "valid"
