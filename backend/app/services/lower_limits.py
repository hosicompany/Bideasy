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
# ⚠️ 경계는 **추정가격**(부가세 제외) 기준이다 — 2026-10-22 확인. 실제 공고의 적격심사 구간명이
#   전부 "추정가격 N억원 미만…"이고, 기초금액 정확히 2억·추정가격 1.82억 공고가 "추정가격 2억원
#   미만" 구간으로 분류됐다. 2026-08 에 "기초금액 기준"으로 정했던 판단(PRICE_BASE_DEFECT.md)은 반대였다.
# 값은 기존 simulation_service.LOWER_LIMITS_2026/OLD 와 동일 (이관·통합).
# ★ KEEP IN SYNC: infra/nginx/html/assets/lower-limits.js (웹 계산기·랜딩 미러) —
#   이 테이블 변경 시 JS 도 함께 수정. tests/test_lower_limits_sync.py 가 드리프트 감시.
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
    estimated_price: float | None = None,
    bid_date: date | None = None,
) -> float:
    """법정 낙찰하한율(%) — **추정가격**으로 금액대 티어를 찾는다.

    Args:
        contract_type: CONSTRUCTION / SERVICE / GOODS
        estimated_price: 추정가격(원, 부가세 제외) = `Notice.basic_price`(presmptPrce).
            기초금액만 있으면 이 함수 대신 `lower_limit_from_basis` 를 쓸 것.
            None 이면 legacy 상수로 폴백.
        bid_date: 공고 기준일. None 이면 오늘 (2026-01-30 이후면 개정 테이블).
    """
    ct = (contract_type or "CONSTRUCTION").upper()
    if ct != "CONSTRUCTION" or not estimated_price or estimated_price <= 0:
        return LEGACY_RATES.get(ct, 87.745)
    d = bid_date or date.today()
    table = _CONSTRUCTION_2026 if d >= CUTOFF_2026 else _CONSTRUCTION_OLD
    for threshold, rate in table:
        if estimated_price >= threshold:
            return rate
    return table[-1][1]


# 기초금액 ÷ 추정가격 실측 비율의 상한. 부가세만이면 1.1 이지만 운영 실측은 0.9877~1.1223 으로
# 흩어진다(services/basis.py) — 1.1 로 잡으면 기초금액 11.1억(추정 9.9억) 공고를 놓친다. 여유를 둬 1.13.
# 기초금액만 알 때 "추정가격이 경계 아래일 수 있는 구간"을 가르는 데만 쓴다.
# ⛔ 기초금액 → 추정가격 환산에 쓰지 말 것(함정 22). 정수 비(×100/113)로 계산해 경계에서 부동소수점이 밀리지 않게 한다.
def _min_estimated(basis_amount: float) -> float:
    return basis_amount * 100 / 113


def lower_limit_from_basis(
    contract_type: str,
    basis_amount: float | None,
    bid_date: date | None = None,
) -> tuple[float, bool]:
    """기초금액만 알 때의 하한율과 '구간 불확실' 여부.

    추정가격은 대략 기초금액 ÷ 1.13 ~ 기초금액 사이다(실측 비율 상한 1.1223). 두 끝의 티어가
    다르면(예: 기초금액 10억~11.3억) 공고를 보기 전엔 어느 쪽인지 모른다. 그때는 **높은 요율**
    (하한선이 높아 무효 쪽으로 새지 않는 쪽)을 쓰고 ambiguous=True 를 돌려준다.
    """
    if not basis_amount or basis_amount <= 0:
        return get_lower_limit_rate(contract_type, None, bid_date), False
    taxed = get_lower_limit_rate(contract_type, _min_estimated(basis_amount), bid_date)
    exempt = get_lower_limit_rate(contract_type, basis_amount, bid_date)
    return max(taxed, exempt), taxed != exempt


def is_plausible_rate(rate: float | None) -> bool:
    """퍼센트 단위 하한율로 볼 수 있는 값인지 — 0.89745 같은 비율 형식·이상치는 버린다."""
    try:
        return rate is not None and 50.0 <= float(rate) <= 100.0
    except (TypeError, ValueError):
        return False


def resolve_lower_limit_rate(
    contract_type: str,
    *,
    notice_rate: float | None = None,
    estimated_price: float | None = None,
    basis_amount: float | None = None,
    bid_date: date | None = None,
) -> tuple[float, str]:
    """공고 하나의 하한율 — 공고 명시값 → 추정가격 티어 → 기초금액(보수) 순.

    반환 출처: "notice" | "estimated" | "basis" | "basis_conservative"(구간 불확실, 높은 쪽 채택)
    """
    if notice_rate and is_plausible_rate(notice_rate):
        return float(notice_rate), "notice"
    if estimated_price and estimated_price > 0:
        return get_lower_limit_rate(contract_type, estimated_price, bid_date), "estimated"
    rate, ambiguous = lower_limit_from_basis(contract_type, basis_amount, bid_date)
    return rate, "basis_conservative" if ambiguous else "basis"


def get_lower_limit_fraction(
    contract_type: str,
    estimated_price: float | None = None,
    bid_date: date | None = None,
) -> float:
    """소수 비율(0.87745 형식) 버전 — simulation_service 호환용(인자는 추정가격)."""
    return get_lower_limit_rate(contract_type, estimated_price, bid_date) / 100.0


# ---------------------------------------------------------------------------
# 금액대 밴드 — 누적 개찰 통계(`opening_stats`)의 집계 축
# ---------------------------------------------------------------------------
# 경계를 위 하한율 테이블과 **같은 지점**으로 잡는다. 하한율이 바뀌는 곳이 곧
# 게임이 바뀌는 곳이라, 다른 경계로 묶으면 성격이 다른 표본이 한 셀에 섞인다.
# ⚠️ 2026-10-22: 하한율 경계는 추정가격 기준인데 이 밴드는 기초금액으로 나눈다. 기초금액 10억~11.3억
#   공고(89.745% 티어)가 10E_50E 셀에 섞일 수 있다 — 누적 개찰 통계 S2 화면 착수 전에 축을 정할 것.
# 경계를 통계 쪽에 따로 적으면 요율 개정 때 두 소스가 갈라진다 — 여기 한 곳에만 둔다.
# (100억 이상과 50~100억은 하한율이 같지만 밴드는 나눈다. 규모가 다르면 참여
#  양상이 다르고, 합칠 일이 생기면 조회 쪽에서 합치는 편이 되돌리기 쉽다.)
AMOUNT_BANDS: list[tuple[int, str, str]] = [
    (10_000_000_000, "GE_100E", "100억 이상"),
    (5_000_000_000, "50E_100E", "50억~100억"),
    (1_000_000_000, "10E_50E", "10억~50억"),
    (300_000_000, "3E_10E", "3억~10억"),
    (0, "LT_3E", "3억 미만"),
]

_BAND_LABELS = {code: label for _, code, label in AMOUNT_BANDS}


def get_amount_band(basic_price: float | None) -> str:
    """기초금액 → 금액대 밴드 코드. 금액을 모르면 빈 문자열.

    ⚠️ 인자는 **기초금액**이다. `Notice.basic_price` 는 추정가격이라 여기 넣으면
    밴드가 한 칸씩 밀린다(docs/PRICE_BASE_DEFECT.md).
    """
    if not basic_price or basic_price <= 0:
        return ""
    for threshold, code, _label in AMOUNT_BANDS:
        if basic_price >= threshold:
            return code
    return AMOUNT_BANDS[-1][1]


def amount_band_label(code: str) -> str:
    """밴드 코드 → 사람이 읽는 라벨. 모르는 코드는 그대로 돌려준다."""
    return _BAND_LABELS.get(code or "", code or "")
