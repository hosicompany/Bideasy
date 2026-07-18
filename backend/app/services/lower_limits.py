"""
낙찰하한율 단일 소스 (Single Source of Truth)
=============================================
2026-07-17 통합: 하한율이 4곳(calculator/tips_generator/simulation_service/
prediction_verifier)에 중복 정의돼 있었고, calculator 계열은 고정 87.745 라
2026-01-30 시행 개정(금액대별 차등)을 반영하지 못했다 — 10억 미만 공사에서
DANGER 판정이 ~2%p 낙관적으로 어긋나는 안전 버그. 이 모듈이 유일한 정본이다.

교차 검증: 우리 개찰 데이터(2021~2025, 4,848건)의 실측 lower_limit_rate 분포
(87.745 / 86.745 / 85.495)가 구(舊) 테이블의 금액대 구간과 정확히 일치함
(docs/BENCHMARK_WIN_REACH.md §1) — 티어드 테이블의 역사적 타당성 확인됨.

주의: 용역(SERVICE)·물품(GOODS)은 계약유형(협상계약·최저가 등)별로 하한
개념이 달라 기존 계산기 정책(60.0 / 0.0)을 유지한다 — 도메인 재검토 전
변경 금지. 시설공사(CONSTRUCTION)만 금액대·시행일 티어드로 판정한다.
"""

from __future__ import annotations

from datetime import date

# 2026-01-30 시행 개정 컷오프
CUTOFF_2026 = date(2026, 1, 30)

# 시설공사 — (추정가격 하한 경계(원), 하한율 %) 내림차순.
# 값은 기존 simulation_service.LOWER_LIMITS_2026/OLD 와 동일 (이관·통합).
_CONSTRUCTION_2026 = [
    (10_000_000_000, 87.495),  # 100억 이상
    (5_000_000_000, 87.495),   # 50억 이상 100억 미만
    (1_000_000_000, 88.745),   # 10억 이상 50억 미만
    (300_000_000, 89.745),     # 3억 이상 10억 미만
    (0, 89.745),               # 3억 미만
]
_CONSTRUCTION_OLD = [
    (10_000_000_000, 85.495),
    (5_000_000_000, 85.495),
    (1_000_000_000, 86.745),
    (300_000_000, 87.745),
    (0, 87.745),
]

# 금액 미상 또는 비공사 계약의 기존(legacy) 정책 — calculator.LOWER_LIMIT_RATES 승계
LEGACY_RATES = {
    "CONSTRUCTION": 87.745,   # 공사 (금액 미상 시 구 기본값 폴백)
    "SERVICE": 60.0,          # 용역 (협상에 의한 계약 등은 다름)
    "GOODS": 0.0,             # 물품 (최저가 방식, 하한선 없음)
}


def get_lower_limit_rate(
    contract_type: str,
    basic_price: float | None = None,
    bid_date: date | None = None,
) -> float:
    """법정 낙찰하한율(%) 조회 — 하한율 판정의 유일한 진입점.

    Args:
        contract_type: CONSTRUCTION / SERVICE / GOODS
        basic_price: 기초금액(원). 공사 금액대 티어 판정에 사용.
            None 이면 legacy 상수로 폴백 (호출부는 가급적 항상 전달할 것).
        bid_date: 공고 기준일. None 이면 오늘 (2026-01-30 이후면 개정 테이블).
    """
    ct = (contract_type or "CONSTRUCTION").upper()
    if ct != "CONSTRUCTION" or not basic_price or basic_price <= 0:
        return LEGACY_RATES.get(ct, 87.745)
    d = bid_date or date.today()
    table = _CONSTRUCTION_2026 if d >= CUTOFF_2026 else _CONSTRUCTION_OLD
    for threshold, rate in table:
        if basic_price >= threshold:
            return rate
    return table[-1][1]


def get_lower_limit_fraction(
    contract_type: str,
    basic_price: float | None = None,
    bid_date: date | None = None,
) -> float:
    """소수 비율(0.87745 형식) 버전 — simulation_service 호환용."""
    return get_lower_limit_rate(contract_type, basic_price, bid_date) / 100.0
