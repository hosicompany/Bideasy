"""
기관 낙찰률 팩트 분석 서비스
============================
원칙 (2026-07-17 정직성 수습 — docs/BENCHMARK_WIN_REACH.md 후속):
- **실데이터(OpeningResult)가 있으면 팩트만 반환한다.**
- **없으면 명시적으로 "데이터 부족"을 반환한다.** (합성/랜덤 데이터 생성 금지)
- 과거 "Demo Mode"의 시드 고정 합성 통계·랜덤 전략 생성은 비예측·정직
  포지션과 충돌하여 전면 제거했다.
"""

import statistics
from typing import Dict, List

from sqlalchemy.orm import Session

from app.db import models

# 통계를 신뢰할 최소 표본 수
MIN_SAMPLE_FOR_STATS = 5

# 표준정규 분위수 (p10/p30/p50/p70/p90) — 분포 요약용
_NORMAL_QUANTILES = [
    (0.10, -1.2816),
    (0.30, -0.5244),
    (0.50, 0.0),
    (0.70, 0.5244),
    (0.90, 1.2816),
]

_INSUFFICIENT = {
    "sample_size": 0,
    "status": "insufficient_data",
    "message": "해당 기관의 개찰 데이터가 아직 충분하지 않습니다.",
}


class WinningRateService:

    @staticmethod
    def get_agency_stats(db: Session, agency_name: str) -> Dict:
        """기관 역대 낙찰률 기술통계 (팩트 전용 — 예측 아님).

        데이터가 없으면 합성값을 만들지 않고 insufficient_data 를 반환한다.
        """
        if not agency_name:
            return dict(_INSUFFICIENT)

        results = (
            db.query(models.OpeningResult)
            .filter(models.OpeningResult.organization.contains(agency_name))
            .all()
        )
        # 유효 범위 필터 (하한선 근처의 정상 낙찰률만)
        rates = [r.winner_rate for r in results if r.winner_rate and 80 < r.winner_rate < 90]

        if len(rates) < MIN_SAMPLE_FOR_STATS:
            out = dict(_INSUFFICIENT)
            out["sample_size"] = len(rates)
            return out

        return {
            "status": "ok",
            "avg_rate": round(statistics.mean(rates), 4),
            "median_rate": round(statistics.median(rates), 4),
            "min_rate": min(rates),
            "max_rate": max(rates),
            "sample_size": len(rates),
            "std_dev": round(statistics.stdev(rates) if len(rates) > 1 else 0, 4),
        }

    @staticmethod
    def run_monte_carlo_simulation(basic_price: float, agency_stats: Dict) -> List[float]:
        """기관 역대 낙찰률 분포의 분위수 요약 (p10/p30/p50/p70/p90).

        과거엔 랜덤 시뮬레이션으로 포장했으나, 실체는 분포 요약이므로
        정규 근사 분위수를 **결정적으로** 계산한다 (동일 입력 → 동일 출력).
        실측 통계가 없으면 빈 리스트를 반환한다 (가짜 구간 생성 금지).
        """
        if agency_stats.get("status") != "ok":
            return []
        center = agency_stats.get("avg_rate")
        sigma = agency_stats.get("std_dev") or 0.0
        if center is None:
            return []
        if sigma <= 0:
            return [round(center, 4)] * len(_NORMAL_QUANTILES)
        return [round(center + z * sigma, 4) for _q, z in _NORMAL_QUANTILES]

    @staticmethod
    def get_blue_ocean_strategy(db: Session, bid_no: str) -> List[Dict]:
        """(구) 블루오션 전략 — 랜덤 생성 문구였으므로 제거.

        실측 경쟁 밀도 분석이 준비되기 전까지는 빈 리스트를 반환한다.
        """
        return []

    @staticmethod
    def predict_competition_rate(db: Session, notice: models.Notice) -> Dict:
        """해당 발주기관의 역대 평균 참가 업체 수 (팩트 — 예측 아님).

        과거엔 지역·유형 하드코딩 배수 + 랜덤 노이즈로 '예측'을 생성했으나,
        실측 개찰 데이터(participants_count)의 기술통계로 대체한다.
        """
        agency_name = getattr(notice, "organization", None) or ""
        counts: List[int] = []
        if agency_name:
            rows = (
                db.query(models.OpeningResult.participants_count)
                .filter(
                    models.OpeningResult.organization.contains(agency_name),
                    models.OpeningResult.participants_count > 0,
                )
                .all()
            )
            counts = [r[0] for r in rows]

        if len(counts) < MIN_SAMPLE_FOR_STATS:
            return {
                "status": "insufficient_data",
                "predicted_count": 0,
                "difficulty": None,
                "message": "해당 기관의 참가 수 데이터가 아직 충분하지 않습니다.",
            }

        avg_count = int(round(statistics.mean(counts)))
        if avg_count > 500:
            difficulty = "HIGH"
            message = f"이 기관의 역대 평균 참가 수는 {avg_count}개사로, 경쟁이 매우 치열한 편이에요."
        elif avg_count > 200:
            difficulty = "MEDIUM"
            message = f"이 기관의 역대 평균 참가 수는 {avg_count}개사로, 평균적인 경쟁률이에요."
        else:
            difficulty = "LOW"
            message = f"이 기관의 역대 평균 참가 수는 {avg_count}개사로, 비교적 쾌적한 편이에요."

        return {
            "status": "ok",
            "basis": "historical_avg",
            "predicted_count": avg_count,
            "sample_size": len(counts),
            "difficulty": difficulty,
            "message": message,
        }
