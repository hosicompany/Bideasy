"""
Advanced Bidding Calculator Service
정밀 투찰가 계산 및 안전도 분석
"""
import math
from dataclasses import dataclass
from typing import Literal
from enum import Enum


class SafetyLevel(str, Enum):
    SAFE = "SAFE"           # 안전한 투찰 구간
    WARNING = "WARNING"     # 주의 (하한선 근접)
    DANGER = "DANGER"       # 위험 (하한선 미달)


@dataclass
class BidCalculationResult:
    """상세 계산 결과"""
    original_price: float           # 기초금액
    rate: float                     # 사정률 (%)
    result_price: int               # 투찰금액 (1원 절사)
    
    # 예정가격 정보
    estimated_price_min: float      # 예정가격 최소 (기초금액 -3%)
    estimated_price_max: float      # 예정가격 최대 (기초금액 +3%)
    
    # 하한선 정보
    lower_limit_rate: float         # 낙찰하한율 (%)
    lower_limit_price: int          # 낙찰하한선 금액 (기초금액 기준)
    lower_limit_price_est_min: int  # 낙찰하한선 (예정가 최소 기준)
    lower_limit_price_est_max: int  # 낙찰하한선 (예정가 최대 기준)
    
    # A값 정보
    a_value: int                    # A값 (국민연금, 건강보험 등 고정비)
    a_value_applied: bool           # A값 적용 여부
    
    # 안전도
    safety_level: SafetyLevel
    distance_from_limit: float      # 하한선 대비 여유율 (%)
    
    # 메시지
    warning_message: str = None


# 법정 낙찰하한선 (국가계약법 기준)
LOWER_LIMIT_RATES = {
    "CONSTRUCTION": 87.745,   # 공사
    "SERVICE": 60.0,          # 용역 (협상에 의한 계약 등은 다름)
    "GOODS": 0.0,             # 물품 (최저가 방식, 하한선 없음)
}

# 예정가격 산정 범위
ESTIMATED_PRICE_VARIANCE = 0.03  # ±3%


class CalculatorService:
    
    @staticmethod
    def get_lower_limit_rate(contract_type: str) -> float:
        """법정 낙찰하한율 조회"""
        return LOWER_LIMIT_RATES.get(contract_type, 87.745)
    
    @staticmethod
    def truncate_to_10_won(price: float) -> int:
        """1원 단위 절사 (10원 미만 버림)"""
        return math.floor(price / 10) * 10
    
    @staticmethod
    def calculate_safe_bid(basic_price: float, rate: float, a_value: float = 0) -> int:
        """
        투찰금액 계산 (A값 반영)
        
        Args:
            basic_price: 기초금액
            rate: 사정률 (예: -5.0 = 기초금액의 95%)
            a_value: A값 (고정비용, 낙찰률 미적용)
        
        Formula:
            A값이 있는 경우: ((기초금액 - A값) * 사정률) + A값
            A값이 없는 경우: 기초금액 * 사정률
        """
        if a_value > 0:
            # A값은 사정률을 적용하지 않고 그대로 유지
            variable_part = basic_price - a_value
            target_price = (variable_part * (1 + rate / 100)) + a_value
        else:
            target_price = basic_price * (1 + rate / 100)
        return CalculatorService.truncate_to_10_won(target_price)
    
    @staticmethod
    def calculate_detailed_bid(
        basic_price: float, 
        rate: float, 
        contract_type: str = "CONSTRUCTION",
        a_value: int = 0
    ) -> BidCalculationResult:
        """
        상세 투찰금액 계산 (A값 반영)
        
        Args:
            basic_price: 기초금액
            rate: 사정률 (%)
            contract_type: 계약 유형
            a_value: A값 (고정비용, 낙찰률 미적용)
        
        Returns:
            BidCalculationResult with all calculation details
        """
        # 1. 투찰금액 계산 (A값 반영)
        result_price = CalculatorService.calculate_safe_bid(basic_price, rate, a_value)
        
        # 2. 예정가격 범위 계산 (기초금액 ±3%)
        est_min = basic_price * (1 - ESTIMATED_PRICE_VARIANCE)
        est_max = basic_price * (1 + ESTIMATED_PRICE_VARIANCE)
        
        # 3. 낙찰하한선 계산
        lower_rate = CalculatorService.get_lower_limit_rate(contract_type)
        
        # 기초금액 기준 하한선
        limit_base = CalculatorService.truncate_to_10_won(
            basic_price * (lower_rate / 100)
        )
        
        # 예정가격 범위 기준 하한선
        limit_est_min = CalculatorService.truncate_to_10_won(
            est_min * (lower_rate / 100)
        )
        limit_est_max = CalculatorService.truncate_to_10_won(
            est_max * (lower_rate / 100)
        )
        
        # 4. 안전도 계산
        # 기초금액 기준 하한선으로 판단 (보수적)
        if result_price < limit_base:
            safety_level = SafetyLevel.DANGER
            warning_msg = f"투찰금액이 낙찰하한선 미만입니다. ({lower_rate}% = {limit_base:,}원)"
        elif result_price < limit_base * 1.02:  # 하한선 +2% 이내
            safety_level = SafetyLevel.WARNING
            warning_msg = f"낙찰하한선({lower_rate}%)에 매우 근접합니다. 주의하세요."
        else:
            safety_level = SafetyLevel.SAFE
            warning_msg = None
        
        # 하한선 대비 여유율 계산
        if limit_base > 0:
            distance = ((result_price - limit_base) / limit_base) * 100
        else:
            distance = 100.0  # 하한선 없음
        
        return BidCalculationResult(
            original_price=basic_price,
            rate=rate,
            result_price=result_price,
            estimated_price_min=est_min,
            estimated_price_max=est_max,
            lower_limit_rate=lower_rate,
            lower_limit_price=limit_base,
            lower_limit_price_est_min=limit_est_min,
            lower_limit_price_est_max=limit_est_max,
            a_value=a_value,
            a_value_applied=a_value > 0,
            safety_level=safety_level,
            distance_from_limit=round(distance, 2),
            warning_message=warning_msg,
        )
    
    @staticmethod
    def get_rate_for_target_price(basic_price: float, target_price: float) -> float:
        """
        목표 투찰금액에 필요한 사정률 역산
        
        Args:
            basic_price: 기초금액
            target_price: 목표 투찰금액
        
        Returns:
            사정률 (%)
        """
        if basic_price <= 0:
            return 0.0
        return ((target_price / basic_price) - 1) * 100
    
    @staticmethod
    def get_safe_rate_range(
        basic_price: float, 
        contract_type: str = "CONSTRUCTION"
    ) -> tuple[float, float]:
        """
        안전한 사정률 범위 계산
        
        Returns:
            (최소 사정률, 최대 사정률)
        """
        lower_rate = CalculatorService.get_lower_limit_rate(contract_type)
        
        # 하한선 기준 최소 사정률
        min_rate = lower_rate - 100  # 예: 87.745 - 100 = -12.255%
        
        # 일반적인 최대 사정률 (예정가격 근처)
        max_rate = 5.0  # +5% 정도가 현실적 상한
        
        return (round(min_rate, 3), max_rate)
