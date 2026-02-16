"""
calculator.py 단위 테스트
=========================
테스트 대상:
1. truncate_to_10_won - 10원 단위 절사
2. calculate_safe_bid - 투찰금액 계산 (A값 포함)
3. calculate_detailed_bid - 상세 계산 + 안전도
4. get_rate_for_target_price - 사정률 역산
5. get_safe_rate_range - 안전 사정률 범위
6. recommend_bid_price - 입찰방법별 최적 투찰가 추천
7. _get_price_bracket - 금액대 구분
"""

import sys
import math
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from app.services.calculator import (
    CalculatorService,
    SafetyLevel,
    LOWER_LIMIT_RATES,
    BID_STRATEGY,
    _get_price_bracket,
)

passed = 0
failed = 0


def check(name, actual, expected):
    global passed, failed
    if actual == expected:
        passed += 1
    else:
        failed += 1
        print(f"  FAIL: {name}")
        print(f"    expected: {expected}")
        print(f"    actual:   {actual}")


def check_close(name, actual, expected, tol=0.01):
    global passed, failed
    if abs(actual - expected) <= tol:
        passed += 1
    else:
        failed += 1
        print(f"  FAIL: {name}")
        print(f"    expected: {expected} (±{tol})")
        print(f"    actual:   {actual}")


# ===== 1. truncate_to_10_won =====
def test_truncate():
    print("[1] truncate_to_10_won")
    t = CalculatorService.truncate_to_10_won

    check("100 → 100", t(100), 100)
    check("105 → 100", t(105), 100)
    check("109 → 100", t(109), 100)
    check("110 → 110", t(110), 110)
    check("0 → 0", t(0), 0)
    check("9 → 0", t(9), 0)
    check("19 → 10", t(19), 10)
    check("1234567 → 1234560", t(1234567), 1234560)
    check("999 → 990", t(999), 990)
    check("소수점 123.7 → 120", t(123.7), 120)
    check("음수 -15 → -20", t(-15), -20)  # math.floor(-1.5) = -2


# ===== 2. calculate_safe_bid =====
def test_safe_bid():
    print("[2] calculate_safe_bid")
    calc = CalculatorService.calculate_safe_bid

    # 기본: 1억 * 0% = 1억
    check("1억 rate=0", calc(100_000_000, 0), 100_000_000)

    # 1억 * (-5%) = 9500만
    check("1억 rate=-5", calc(100_000_000, -5.0), 95_000_000)

    # 1억 * (-12.255%) = 87,745,000
    check("1억 rate=-12.255", calc(100_000_000, -12.255), 87_745_000)

    # 10원 미만 절사 확인: 50,000,000 * (1 - 0.123%) = 49,938,500
    result = calc(50_000_000, -0.123)
    check("5천만 rate=-0.123 10원단위", result % 10, 0)

    # A값 있는 경우: ((1억 - 1천만) * 95%) + 1천만 = 9550만
    # = (90,000,000 * 0.95) + 10,000,000 = 85,500,000 + 10,000,000 = 95,500,000
    check("A값 적용", calc(100_000_000, -5.0, a_value=10_000_000), 95_500_000)

    # A값 = 0이면 적용 안됨
    check("A값=0", calc(100_000_000, -5.0, a_value=0), 95_000_000)

    # A값이 기초금액과 같으면: ((1억-1억)*95%) + 1억 = 1억
    check("A값=기초금액", calc(100_000_000, -5.0, a_value=100_000_000), 100_000_000)


# ===== 3. calculate_detailed_bid =====
def test_detailed_bid():
    print("[3] calculate_detailed_bid")
    calc = CalculatorService.calculate_detailed_bid

    # 공사, 1억, rate=0
    r = calc(100_000_000, 0, "CONSTRUCTION")
    check("원가", r.original_price, 100_000_000)
    check("rate", r.rate, 0)
    check("result_price", r.result_price, 100_000_000)
    check("하한율", r.lower_limit_rate, 87.745)
    check("A값 미적용", r.a_value_applied, False)

    # 예정가격 범위: 1억 ±3%
    check_close("예정가min", r.estimated_price_min, 97_000_000)
    check_close("예정가max", r.estimated_price_max, 103_000_000)

    # 하한선: 1억 * 87.745% = 87,745,000
    check("하한선", r.lower_limit_price, 87_745_000)

    # 안전도: 1억 > 하한선 87,745,000 * 1.02 = 89,499,900 → SAFE
    check("safety SAFE", r.safety_level, SafetyLevel.SAFE)

    # 하한선 미달: rate = -13%  → 87,000,000 < 87,745,000 → DANGER
    r2 = calc(100_000_000, -13.0, "CONSTRUCTION")
    check("safety DANGER", r2.safety_level, SafetyLevel.DANGER)
    check("DANGER warning not None", r2.warning_message is not None, True)

    # 하한선 근접: rate = -12.1% → 87,900,000. 하한선 87,745,000 * 1.02 = 89,499,900
    # 87,900,000 < 89,499,900 → WARNING
    r3 = calc(100_000_000, -12.1, "CONSTRUCTION")
    check("safety WARNING", r3.safety_level, SafetyLevel.WARNING)

    # 용역: 하한율 60%
    r4 = calc(100_000_000, 0, "SERVICE")
    check("용역 하한율", r4.lower_limit_rate, 60.0)
    check("용역 하한선", r4.lower_limit_price, 60_000_000)

    # 물품: 하한율 0%
    r5 = calc(100_000_000, 0, "GOODS")
    check("물품 하한율", r5.lower_limit_rate, 0.0)
    check("물품 하한선", r5.lower_limit_price, 0)
    check("물품 distance", r5.distance_from_limit, 100.0)

    # A값 적용
    r6 = calc(100_000_000, -5.0, "CONSTRUCTION", a_value=10_000_000)
    check("A값 적용됨", r6.a_value_applied, True)
    check("A값", r6.a_value, 10_000_000)
    check("A값 투찰가", r6.result_price, 95_500_000)


# ===== 4. get_rate_for_target_price =====
def test_rate_for_target():
    print("[4] get_rate_for_target_price")
    calc = CalculatorService.get_rate_for_target_price

    # 1억 → 9500만: rate = -5%
    check_close("역산 -5%", calc(100_000_000, 95_000_000), -5.0)

    # 1억 → 1억: rate = 0%
    check_close("역산 0%", calc(100_000_000, 100_000_000), 0.0)

    # 1억 → 1.05억: rate = 5%
    check_close("역산 +5%", calc(100_000_000, 105_000_000), 5.0)

    # 기초금액 0이면 0
    check("기초금액=0", calc(0, 50_000_000), 0.0)

    # 기초금액 음수
    check("기초금액<0", calc(-100, 50), 0.0)


# ===== 5. get_safe_rate_range =====
def test_safe_rate_range():
    print("[5] get_safe_rate_range")
    calc = CalculatorService.get_safe_rate_range

    min_r, max_r = calc(100_000_000, "CONSTRUCTION")
    check_close("공사 최소율", min_r, -12.255)
    check("공사 최대율", max_r, 5.0)

    min_r2, max_r2 = calc(100_000_000, "SERVICE")
    check_close("용역 최소율", min_r2, -40.0)

    min_r3, max_r3 = calc(100_000_000, "GOODS")
    check_close("물품 최소율", min_r3, -100.0)


# ===== 6. _get_price_bracket =====
def test_price_bracket():
    print("[6] _get_price_bracket")

    check("5천만 → small", _get_price_bracket(50_000_000), "small")
    check("9999만 → small", _get_price_bracket(99_999_999), "small")
    check("1억 → medium", _get_price_bracket(100_000_000), "medium")
    check("3억 → medium", _get_price_bracket(300_000_000), "medium")
    check("4.99억 → medium", _get_price_bracket(499_999_999), "medium")
    check("5억 → large", _get_price_bracket(500_000_000), "large")
    check("9.99억 → large", _get_price_bracket(999_999_999), "large")
    check("10억 → xlarge", _get_price_bracket(1_000_000_000), "xlarge")
    check("30억 → xlarge", _get_price_bracket(3_000_000_000), "xlarge")
    check("49.9억 → xlarge", _get_price_bracket(4_999_999_999), "xlarge")
    check("50억 → xxlarge", _get_price_bracket(5_000_000_000), "xxlarge")
    check("100억 → xxlarge", _get_price_bracket(10_000_000_000), "xxlarge")
    check("0 → small", _get_price_bracket(0), "small")


# ===== 7. recommend_bid_price =====
def test_recommend():
    print("[7] recommend_bid_price")
    rec = CalculatorService.recommend_bid_price

    # 적격심사제, 3억 (medium)
    r = rec(300_000_000, "적격심사제")
    check("bracket medium", r["bracket"], "medium")
    check("bid_method", r["bid_method"], "적격심사제")
    # 하한율 87.745 + 여유분 0.2 = 87.945%
    check_close("target_rate", r["target_rate_pct"], 87.945)
    check("10원단위", r["recommended_price"] % 10, 0)
    # 보정 +0.7%
    check_close("adjustment", r["adjustment"], 0.7)
    # 투찰가: 300,000,000 * (1+0.7/100) * 87.945%
    pred_price = 300_000_000 * (1 + 0.7 / 100)
    expected_price = math.floor(pred_price * 87.945 / 100 / 10) * 10
    check("투찰가", r["recommended_price"], expected_price)

    # 소액수의견적, 5천만 (small)
    r2 = rec(50_000_000, "소액수의견적")
    check("bracket small", r2["bracket"], "small")
    # 보정 -0.2%, 여유분 0.9 → 88.645%
    check_close("target_rate 소액", r2["target_rate_pct"], 88.645)
    check_close("adjustment 소액", r2["adjustment"], -0.2)
    # 투찰가: 50,000,000 * (1-0.2/100) * 88.645%
    pred2 = 50_000_000 * (1 - 0.2 / 100)
    expected2 = math.floor(pred2 * 88.645 / 100 / 10) * 10
    check("투찰가 소액", r2["recommended_price"], expected2)

    # 적격심사제, 10억 (xlarge)
    r3 = rec(1_000_000_000, "적격심사제")
    check("bracket xlarge", r3["bracket"], "xlarge")
    check_close("adjustment xlarge", r3["adjustment"], -0.2)
    check_close("margin xlarge", r3["margin"], 0.9)

    # 알 수 없는 입찰방법 → DEFAULT
    r4 = rec(200_000_000, "알수없는방법")
    check("unknown → DEFAULT medium", r4["bracket"], "medium")
    check_close("unknown adj", r4["adjustment"], 0.5)

    # A값 적용
    r5 = rec(100_000_000, "적격심사제", a_value=10_000_000)
    # A값 있으면 투찰가가 더 높아야 함 (고정비 보존)
    r5_no_a = rec(100_000_000, "적격심사제", a_value=0)
    check("A값 적용시 더 높음", r5["recommended_price"] > r5_no_a["recommended_price"], True)

    # 기초금액 0
    r6 = rec(0, "적격심사제")
    check("기초금액0 투찰가", r6["recommended_price"], 0)

    # strategy_desc가 포함되어 있는지
    check("desc 존재", "strategy_desc" in r, True)
    check("desc 내용", "하한율" in r["strategy_desc"], True)


# ===== 실행 =====
def main():
    print("=" * 50)
    print("  calculator.py 단위 테스트")
    print("=" * 50)
    print()

    test_truncate()
    test_safe_bid()
    test_detailed_bid()
    test_rate_for_target()
    test_safe_rate_range()
    test_price_bracket()
    test_recommend()

    print()
    print("=" * 50)
    total = passed + failed
    if failed == 0:
        print(f"  ALL PASSED ({passed}/{total})")
    else:
        print(f"  {failed} FAILED / {passed} passed (total {total})")
    print("=" * 50)
    return failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
