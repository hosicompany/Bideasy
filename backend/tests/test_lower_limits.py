"""
낙찰하한율 단일 소스(lower_limits) 회귀 테스트
================================================
2026-07-17 통합: 공사 하한율이 고정 87.745 로 하드코딩돼 2026-01-30 개정
(금액대별 차등)을 반영 못 하던 안전 버그 수정 검증.
"""

from datetime import date

from app.services.calculator import CalculatorService, SafetyLevel
from app.services.lower_limits import get_lower_limit_rate


AFTER = date(2026, 7, 1)    # 개정 이후
BEFORE = date(2025, 7, 1)   # 개정 이전


class TestTieredRates:
    def test_construction_2026_tiers(self):
        assert get_lower_limit_rate("CONSTRUCTION", 100_000_000, AFTER) == 89.745    # 3억 미만
        assert get_lower_limit_rate("CONSTRUCTION", 500_000_000, AFTER) == 89.745    # 3~10억
        assert get_lower_limit_rate("CONSTRUCTION", 2_000_000_000, AFTER) == 88.745  # 10~50억
        assert get_lower_limit_rate("CONSTRUCTION", 20_000_000_000, AFTER) == 87.495 # 100억+

    def test_construction_old_tiers(self):
        # 구 테이블 — 우리 개찰 데이터 실측 llr 분포(87.745/86.745/85.495)와 일치
        assert get_lower_limit_rate("CONSTRUCTION", 100_000_000, BEFORE) == 87.745
        assert get_lower_limit_rate("CONSTRUCTION", 2_000_000_000, BEFORE) == 86.745
        assert get_lower_limit_rate("CONSTRUCTION", 20_000_000_000, BEFORE) == 85.495

    def test_cutoff_boundary(self):
        assert get_lower_limit_rate("CONSTRUCTION", 100_000_000, date(2026, 1, 29)) == 87.745
        assert get_lower_limit_rate("CONSTRUCTION", 100_000_000, date(2026, 1, 30)) == 89.745

    def test_service_goods_legacy_unchanged(self):
        # 용역·물품은 기존 정책 유지 (도메인 재검토 전 변경 금지)
        assert get_lower_limit_rate("SERVICE", 100_000_000, AFTER) == 60.0
        assert get_lower_limit_rate("GOODS", 100_000_000, AFTER) == 0.0

    def test_no_price_falls_back_to_legacy(self):
        # 하위 호환: 금액 미전달 시 구 상수
        assert get_lower_limit_rate("CONSTRUCTION") == 87.745
        assert CalculatorService.get_lower_limit_rate("CONSTRUCTION") == 87.745


class TestDangerJudgmentFix:
    """수정 전 낙관 오판 케이스: 1억 공사를 88.5%로 투찰.

    구 코드는 하한 87.745% 기준 '통과(WARNING)'로 판정했지만,
    2026 개정 기준 실제 하한은 89.745% — 무효 투찰이다.
    """

    def test_small_construction_danger_now_correct(self):
        result = CalculatorService.calculate_detailed_bid(
            basic_price=100_000_000, rate=-11.5, contract_type="CONSTRUCTION"
        )
        # 88,500,000 < 89,745,000 (하한선) → DANGER
        assert result.lower_limit_rate == 89.745
        assert result.result_price == 88_500_000
        assert result.safety_level == SafetyLevel.DANGER

    def test_small_construction_safe_above_new_limit(self):
        result = CalculatorService.calculate_detailed_bid(
            basic_price=100_000_000, rate=-8.0, contract_type="CONSTRUCTION"
        )
        # 92,000,000 > 89,745,000 × 1.02 → SAFE
        assert result.safety_level == SafetyLevel.SAFE

    def test_large_construction_uses_lower_tier(self):
        # 100억+ 공사는 87.495% — 소규모보다 낮은 하한
        result = CalculatorService.calculate_detailed_bid(
            basic_price=20_000_000_000, rate=-11.5, contract_type="CONSTRUCTION"
        )
        assert result.lower_limit_rate == 87.495
        assert result.safety_level != SafetyLevel.DANGER
