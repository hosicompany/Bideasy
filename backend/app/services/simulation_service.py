"""
나라장터 투찰 시뮬레이션 서비스
- 몬테카를로 시뮬레이션 기반 예정가격 예측
- 규칙 기반 최적 투찰가 추천
- 2026년 규정 반영

참고: Gemini Deep Research 보고서 기반
"""

import numpy as np
from typing import Dict, Any, Optional, Tuple
from dataclasses import dataclass
from datetime import date
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class BidType(Enum):
    """입찰 업종"""
    CONSTRUCTION = "construction"  # 시설공사
    GOODS = "goods"  # 물품
    SERVICE = "service"  # 용역


class AgencyType(Enum):
    """발주기관 유형"""
    NATIONAL = "national"  # 조달청/국가기관 (±2%)
    LOCAL = "local"  # 지방자치단체 (±3%)
    PUBLIC_CORP = "public_corp"  # 공기업 (주로 ±2%)


@dataclass
class SimulationConfig:
    """시뮬레이션 설정"""
    num_simulations: int = 100000  # 몬테카를로 반복 횟수
    num_preliminary_prices: int = 15  # 복수예비가격 개수
    num_selected: int = 4  # 추첨 개수


class BidSimulationService:
    """투찰 시뮬레이션 서비스"""
    
    # 2026년 낙찰하한율 (2026.1.30 시행)
    LOWER_LIMITS_2026 = {
        # 시설공사
        "construction": {
            "100억 이상": 0.87495,
            "50억 이상 100억 미만": 0.87495,
            "10억 이상 50억 미만": 0.88745,
            "3억 이상 10억 미만": 0.89745,
            "3억 미만": 0.89745,
        },
        # 물품
        "goods": {
            "2.1억 이상": 0.80495,
            "2.1억 미만": 0.84245,
            "중소기업간 경쟁": 0.87995,
        },
        # 용역
        "service": {
            "일반": 0.87995,
            "단순노무": 0.87745,
        }
    }
    
    # 기존 낙찰하한율 (~2026.1.29)
    LOWER_LIMITS_OLD = {
        "construction": {
            "100억 이상": 0.85495,
            "50억 이상 100억 미만": 0.85495,
            "10억 이상 50억 미만": 0.86745,
            "3억 이상 10억 미만": 0.87745,
            "3억 미만": 0.87745,
        },
        "goods": {
            "2.1억 이상": 0.80495,
            "2.1억 미만": 0.84245,
            "중소기업간 경쟁": 0.87995,
        },
        "service": {
            "일반": 0.87745,
            "단순노무": 0.87745,
        }
    }
    
    # 예가 변동 범위
    PRICE_RANGES = {
        AgencyType.NATIONAL: 0.02,  # ±2%
        AgencyType.LOCAL: 0.03,  # ±3%
        AgencyType.PUBLIC_CORP: 0.02,  # ±2% (대부분)
    }
    
    def __init__(self, config: SimulationConfig = None):
        self.config = config or SimulationConfig()
    
    def generate_preliminary_prices(
        self,
        base_amount: float,
        agency_type: AgencyType = AgencyType.NATIONAL,
        round_unit: int = 1
    ) -> np.ndarray:
        """
        복수예비가격 15개 생성 (층화 표본 추출)
        
        Args:
            base_amount: 기초금액
            agency_type: 발주기관 유형
            round_unit: 반올림 단위 (1원 or 10원)
        
        Returns:
            15개의 복수예비가격 배열
        """
        price_range = self.PRICE_RANGES[agency_type]
        num_prices = self.config.num_preliminary_prices
        
        # 전체 범위를 15개 구간으로 분할
        min_rate = 1.0 - price_range
        max_rate = 1.0 + price_range
        
        # 각 구간별로 하나씩 난수 생성 (층화 표본 추출)
        bucket_size = (max_rate - min_rate) / num_prices
        prices = []
        
        for i in range(num_prices):
            bucket_min = min_rate + (i * bucket_size)
            bucket_max = min_rate + ((i + 1) * bucket_size)
            rate = np.random.uniform(bucket_min, bucket_max)
            price = base_amount * rate
            
            # 반올림 처리
            if round_unit == 10:
                price = np.ceil(price / 10) * 10  # 10원 단위 절상
            else:
                price = np.floor(price)  # 1원 단위 절사
            
            prices.append(price)
        
        return np.array(prices)
    
    def calculate_planned_price(self, preliminary_prices: np.ndarray) -> float:
        """
        예정가격 계산 (4개 추첨 평균)
        
        실제 시스템: 입찰자 선택 빈도 상위 4개
        시뮬레이션: 무작위 4개 선택 (균등 확률)
        """
        selected_indices = np.random.choice(
            len(preliminary_prices), 
            size=self.config.num_selected, 
            replace=False
        )
        selected_prices = preliminary_prices[selected_indices]
        
        # 평균 계산 후 절사
        planned_price = np.floor(np.mean(selected_prices))
        
        return planned_price
    
    def run_monte_carlo(
        self,
        base_amount: float,
        agency_type: AgencyType = AgencyType.NATIONAL,
        num_simulations: int = None
    ) -> Dict[str, Any]:
        """
        몬테카를로 시뮬레이션 실행
        
        Returns:
            예정가격 분포 통계
        """
        if num_simulations is None:
            num_simulations = self.config.num_simulations
        
        planned_prices = []
        
        for _ in range(num_simulations):
            # 1. 복수예비가격 생성
            preliminary = self.generate_preliminary_prices(base_amount, agency_type)
            # 2. 예정가격 결정
            planned = self.calculate_planned_price(preliminary)
            planned_prices.append(planned)
        
        planned_prices = np.array(planned_prices)
        
        return {
            "mean": float(np.mean(planned_prices)),
            "median": float(np.median(planned_prices)),
            "std": float(np.std(planned_prices)),
            "min": float(np.min(planned_prices)),
            "max": float(np.max(planned_prices)),
            "percentile_5": float(np.percentile(planned_prices, 5)),
            "percentile_25": float(np.percentile(planned_prices, 25)),
            "percentile_75": float(np.percentile(planned_prices, 75)),
            "percentile_95": float(np.percentile(planned_prices, 95)),
            "num_simulations": num_simulations,
        }
    
    def get_lower_limit(
        self,
        bid_type: str,
        estimated_amount: float,
        bid_date: date = None,
        is_sme_competition: bool = False
    ) -> float:
        """
        낙찰하한율 조회
        
        Args:
            bid_type: 입찰 유형 (construction, goods, service)
            estimated_amount: 추정가격
            bid_date: 입찰일 (2026.1.30 기준 분기)
            is_sme_competition: 중소기업간 경쟁 여부
        """
        if bid_date is None:
            bid_date = date.today()
        
        # 2026.1.30 이후 신규 하한율 적용
        cutoff_date = date(2026, 1, 30)
        limits = self.LOWER_LIMITS_2026 if bid_date >= cutoff_date else self.LOWER_LIMITS_OLD
        
        if bid_type == "construction":
            if estimated_amount >= 10_000_000_000:
                return limits["construction"]["100억 이상"]
            elif estimated_amount >= 5_000_000_000:
                return limits["construction"]["50억 이상 100억 미만"]
            elif estimated_amount >= 1_000_000_000:
                return limits["construction"]["10억 이상 50억 미만"]
            elif estimated_amount >= 300_000_000:
                return limits["construction"]["3억 이상 10억 미만"]
            else:
                return limits["construction"]["3억 미만"]
        
        elif bid_type == "goods":
            if is_sme_competition:
                return limits["goods"]["중소기업간 경쟁"]
            elif estimated_amount >= 210_000_000:
                return limits["goods"]["2.1억 이상"]
            else:
                return limits["goods"]["2.1억 미만"]
        
        elif bid_type == "service":
            return limits["service"]["일반"]
        
        return 0.87745  # 기본값
    
    def calculate_optimal_bid(
        self,
        base_amount: float,
        a_value: float = 0,
        bid_type: str = "construction",
        estimated_amount: float = None,
        bid_date: date = None,
        agency_type: AgencyType = AgencyType.NATIONAL,
        margin_pct: float = None,
        agency_name: str = "",
    ) -> Dict[str, Any]:
        """
        최적 투찰가 계산

        Args:
            base_amount: 기초금액
            a_value: A값 (시설공사용)
            bid_type: 입찰 유형
            estimated_amount: 추정가격 (하한율 결정용)
            bid_date: 입찰일
            agency_type: 발주기관 유형
            margin_pct: 수동 마진 (None이면 참여수 기반 자동 결정)
            agency_name: 발주기관명 (참여수 예측용)

        Returns:
            최적 투찰가 및 시뮬레이션 결과
        """
        if estimated_amount is None:
            estimated_amount = base_amount

        if bid_date is None:
            bid_date = date.today()

        # 1. 몬테카를로 시뮬레이션으로 예정가격 분포 예측
        price_distribution = self.run_monte_carlo(
            base_amount=base_amount,
            agency_type=agency_type,
            num_simulations=10000  # 빠른 응답을 위해 축소
        )

        # 2. 낙찰하한율 조회
        lower_limit = self.get_lower_limit(
            bid_type=bid_type,
            estimated_amount=estimated_amount,
            bid_date=bid_date
        )

        # 3. 참여수 예측 및 동적 마진 결정
        competition_analysis = None
        if margin_pct is None:
            margin_pct, competition_analysis = self._get_dynamic_margin(
                bid_type=bid_type,
                estimated_amount=estimated_amount,
                agency_name=agency_name,
                bid_date=bid_date,
            )

        # 4. 예정가격 예상 범위
        expected_planned_price = price_distribution["mean"]

        # 5. 최적 투찰가 계산 (하한율 + 동적 마진)
        effective_rate = lower_limit + (margin_pct / 100.0)

        if bid_type == "construction" and a_value > 0:
            # 시설공사: (예정가격 - A값) × 투찰률 + A값
            optimal_bid = (expected_planned_price - a_value) * effective_rate + a_value
        else:
            # 물품/용역: 예정가격 × 투찰률
            optimal_bid = expected_planned_price * effective_rate

        # 절상 (1원 단위)
        optimal_bid = np.ceil(optimal_bid)

        # 6. 투찰률 범위 계산
        bid_rate_at_mean = optimal_bid / expected_planned_price * 100
        bid_rate_at_low = optimal_bid / price_distribution["percentile_95"] * 100
        bid_rate_at_high = optimal_bid / price_distribution["percentile_5"] * 100

        # 7. 동가 위험도 판단
        tie_risk = "high" if abs(bid_rate_at_mean - lower_limit * 100) < 0.01 else "medium"

        # 8. 회피 권장 구간 (동가 위험 구간)
        danger_zone = lower_limit * expected_planned_price

        result = {
            "optimal_bid": float(optimal_bid),
            "lower_limit": lower_limit,
            "lower_limit_pct": f"{lower_limit * 100:.3f}%",
            "applied_margin_pct": margin_pct,
            "effective_rate": round(effective_rate * 100, 3),
            "expected_planned_price": {
                "mean": price_distribution["mean"],
                "range": {
                    "low": price_distribution["percentile_5"],
                    "high": price_distribution["percentile_95"]
                }
            },
            "bid_rate": {
                "at_mean": round(bid_rate_at_mean, 3),
                "at_low_planned": round(bid_rate_at_low, 3),
                "at_high_planned": round(bid_rate_at_high, 3)
            },
            "tie_risk": tie_risk,
            "danger_zone": float(danger_zone),
            "recommendation": self._generate_recommendation(
                optimal_bid, danger_zone, tie_risk, lower_limit, margin_pct,
                competition_analysis
            ),
            "input": {
                "base_amount": base_amount,
                "a_value": a_value,
                "bid_type": bid_type,
                "agency_type": agency_type.value,
                "bid_date": bid_date.isoformat()
            },
            "regulation_version": "2026" if bid_date >= date(2026, 1, 30) else "legacy"
        }

        if competition_analysis:
            result["competition"] = competition_analysis

        return result

    def _get_dynamic_margin(
        self,
        bid_type: str,
        estimated_amount: float,
        agency_name: str,
        bid_date: date,
    ) -> Tuple[float, Optional[Dict]]:
        """참여수 예측 기반 동적 마진 결정"""
        try:
            from app.services.participant_prediction_service import (
                get_participant_prediction_service,
                DYNAMIC_MARGINS,
            )
            service = get_participant_prediction_service()
            prediction = service.predict(
                bid_type=bid_type,
                estimated_amount=estimated_amount,
                agency_name=agency_name,
                bid_date=bid_date,
            )
            bucket = prediction["predicted_bucket"]
            margin = DYNAMIC_MARGINS[bucket]["margin"]
            return margin, {
                "predicted_participants": prediction["predicted_count"],
                "competition_level": prediction["competition_level"],
                "blue_ocean_probability": prediction["blue_ocean_probability"],
                "recommended_margin": margin,
            }
        except Exception as e:
            logger.warning(f"참여수 예측 실패, 기본 마진 사용: {e}")
            return 0.01, None
    
    def _generate_recommendation(
        self,
        optimal_bid: float,
        danger_zone: float,
        tie_risk: str,
        lower_limit: float,
        margin_pct: float = 0,
        competition: Optional[Dict] = None,
    ) -> str:
        """추천 메시지 생성"""
        parts = []

        # 경쟁 강도 정보
        if competition:
            level = competition["competition_level"]
            count = competition["predicted_participants"]
            parts.append(f"예상 참여 {count}명({level})")

        if tie_risk == "high":
            safe_bid = np.ceil(optimal_bid * 1.001)
            parts.append(f"동가 위험! {safe_bid:,.0f}원으로 약간 높게 투찰 권장")
        else:
            effective = lower_limit * 100 + margin_pct
            parts.append(f"추천 투찰가: {optimal_bid:,.0f}원 ({effective:.3f}%)")

        return " | ".join(parts)


# 싱글톤 인스턴스
_simulation_service: Optional[BidSimulationService] = None


def get_simulation_service() -> BidSimulationService:
    """시뮬레이션 서비스 인스턴스 반환"""
    global _simulation_service
    if _simulation_service is None:
        _simulation_service = BidSimulationService()
    return _simulation_service
