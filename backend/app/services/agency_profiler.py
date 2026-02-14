"""기관 프로파일링 서비스 — 낙찰 패턴 분석"""
from typing import List, Optional
from app.services.opening_result import OpeningResultService


class AgencyProfiler:

    @staticmethod
    def analyze(organization: str, months: int = 6) -> dict:
        """
        기관별 과거 낙찰 데이터를 수집하고 패턴을 분석.
        """
        # 1. 과거 개찰 데이터 수집
        history = OpeningResultService.crawl_agency_history(organization, months)

        if not history:
            return {
                "organization": organization,
                "total_bids": 0,
                "avg_winning_rate": None,
                "min_winning_rate": None,
                "max_winning_rate": None,
                "avg_participants": None,
                "avg_winning_price": None,
                "winning_rate_distribution": {},
                "recommendation": f"{organization}의 최근 {months}개월 낙찰 데이터가 없습니다.",
            }

        # 2. 낙찰률 추출 (0 제외)
        rates = [h["winner_rate"] for h in history if h.get("winner_rate", 0) > 0]
        prices = [h["winner_price"] for h in history if h.get("winner_price", 0) > 0]

        total_bids = len(history)
        avg_rate = sum(rates) / len(rates) if rates else None
        min_rate = min(rates) if rates else None
        max_rate = max(rates) if rates else None
        avg_price = sum(prices) / len(prices) if prices else None

        # 3. 낙찰률 구간별 분포
        distribution = AgencyProfiler._calculate_distribution(rates)

        # 4. 투찰 전략 추천
        recommendation = AgencyProfiler._generate_recommendation(
            organization, total_bids, avg_rate, min_rate, max_rate, distribution
        )

        return {
            "organization": organization,
            "total_bids": total_bids,
            "avg_winning_rate": round(avg_rate, 3) if avg_rate else None,
            "min_winning_rate": round(min_rate, 3) if min_rate else None,
            "max_winning_rate": round(max_rate, 3) if max_rate else None,
            "avg_participants": None,  # API에서 제공 안 하는 경우 None
            "avg_winning_price": round(avg_price) if avg_price else None,
            "winning_rate_distribution": distribution,
            "recommendation": recommendation,
        }

    @staticmethod
    def _calculate_distribution(rates: List[float]) -> dict:
        """낙찰률을 구간별로 분류"""
        if not rates:
            return {}

        buckets = {
            "87.745~88.0%": 0,
            "88.0~88.5%": 0,
            "88.5~89.0%": 0,
            "89.0~90.0%": 0,
            "90.0% 이상": 0,
            "87.745% 미만": 0,
        }

        for r in rates:
            if r < 87.745:
                buckets["87.745% 미만"] += 1
            elif r < 88.0:
                buckets["87.745~88.0%"] += 1
            elif r < 88.5:
                buckets["88.0~88.5%"] += 1
            elif r < 89.0:
                buckets["88.5~89.0%"] += 1
            elif r < 90.0:
                buckets["89.0~90.0%"] += 1
            else:
                buckets["90.0% 이상"] += 1

        # 빈 구간 제거
        return {k: v for k, v in buckets.items() if v > 0}

    @staticmethod
    def _generate_recommendation(
        org: str,
        total: int,
        avg_rate: Optional[float],
        min_rate: Optional[float],
        max_rate: Optional[float],
        distribution: dict,
    ) -> str:
        """데이터 기반 투찰 전략 추천 (예측 아님, 팩트 기반)"""
        if not avg_rate:
            return f"{org}의 낙찰 데이터가 부족하여 분석이 어렵습니다."

        parts = []
        parts.append(f"{org}의 최근 {total}건 낙찰 데이터 기준,")
        parts.append(f"평균 낙찰률은 {avg_rate:.3f}%입니다.")

        if max_rate and min_rate:
            spread = max_rate - min_rate
            if spread < 0.5:
                parts.append(f"낙찰률 편차가 {spread:.3f}%로 매우 좁아, 경쟁이 치열한 기관입니다.")
            elif spread < 1.5:
                parts.append(f"낙찰률 편차가 {spread:.3f}%로 보통 수준입니다.")
            else:
                parts.append(f"낙찰률 편차가 {spread:.3f}%로 넓어, 변동성이 큰 기관입니다.")

        # 가장 많은 구간 찾기
        if distribution:
            top_bucket = max(distribution, key=distribution.get)
            parts.append(f"가장 많은 낙찰이 {top_bucket} 구간에서 발생했습니다.")

        return " ".join(parts)
