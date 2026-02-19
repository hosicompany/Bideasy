"""
유형별 낙찰률 예측 서비스
- 물품/용역: 분산이 커서 ML 예측이 효과적
- 공사: 참여수 많으면 하한율 수렴 → 참여수 기반 전략이 우선
- 기관별 과거 낙찰률 통계 제공
"""

import joblib
import numpy as np
from pathlib import Path
from typing import Dict, Any, Optional, List
from datetime import date
import logging

logger = logging.getLogger(__name__)


class BidRatePredictionService:
    """유형별 낙찰률 예측 서비스"""

    def __init__(self, model_path: Optional[Path] = None):
        if model_path is None:
            model_path = Path(__file__).parent.parent.parent / "models" / "bidrate_by_type.joblib"

        self.model_path = model_path
        self.models = {}
        self.features = []
        self.metrics = {}
        self.agency_bid_stats = {}

        self._load_model()

    def _load_model(self):
        """모델 로드"""
        try:
            data = joblib.load(self.model_path)
            self.models = data['models']
            self.features = data['features']
            self.metrics = data.get('metrics', {})
            self.agency_bid_stats = data.get('agency_bid_stats', {})
            logger.info(f"유형별 낙찰률 모델 로드 완료: {list(self.models.keys())}")
        except Exception as e:
            logger.error(f"유형별 낙찰률 모델 로드 실패: {e}")
            raise

    def predict_bid_rate(
        self,
        bid_type: str,
        estimated_amount: float,
        expected_participants: int = 10,
        agency_name: str = "",
        bid_date: Optional[date] = None,
    ) -> Dict[str, Any]:
        """
        낙찰률 예측

        Args:
            bid_type: 입찰 유형 (construction, goods, service)
            estimated_amount: 추정 금액
            expected_participants: 예상 참여업체수
            agency_name: 발주기관명
            bid_date: 입찰일
        """
        if bid_type not in self.models:
            raise ValueError(f"지원하지 않는 입찰 유형: {bid_type}")

        if bid_date is None:
            bid_date = date.today()

        model = self.models[bid_type]
        features = self._create_features(
            estimated_amount=estimated_amount,
            expected_participants=expected_participants,
            agency_name=agency_name,
            bid_date=bid_date,
        )

        predicted_rate = float(model.predict([features])[0])
        predicted_rate = max(50, min(100, predicted_rate))

        # 모델 MAE 기반 신뢰구간
        mae = self.metrics.get(bid_type, {}).get('mae', 3.0)
        lower_bound = max(50, predicted_rate - mae * 1.5)
        upper_bound = min(100, predicted_rate + mae * 1.5)

        # 기관 통계
        agency_stat = self._get_agency_stat(bid_type, agency_name)

        # 예측 신뢰도
        confidence = self._calc_confidence(
            bid_type, estimated_amount, expected_participants, agency_stat
        )

        return {
            "predicted_rate": round(predicted_rate, 2),
            "confidence": confidence,
            "range": {
                "lower": round(lower_bound, 2),
                "upper": round(upper_bound, 2),
            },
            "model_metrics": {
                "mae": round(mae, 2),
                "r2": round(self.metrics.get(bid_type, {}).get('r2', 0), 4),
            },
            "agency_reference": agency_stat,
            "input": {
                "bid_type": bid_type,
                "estimated_amount": estimated_amount,
                "expected_participants": expected_participants,
                "agency_name": agency_name,
            },
        }

    def _create_features(
        self,
        estimated_amount: float,
        expected_participants: int,
        agency_name: str,
        bid_date: date,
    ) -> list:
        """특성 벡터 생성"""
        log_estimated_price = np.log1p(estimated_amount)

        if estimated_amount <= 5e7:
            amount_category = 0
        elif estimated_amount <= 1e8:
            amount_category = 1
        elif estimated_amount <= 3e8:
            amount_category = 2
        elif estimated_amount <= 10e8:
            amount_category = 3
        elif estimated_amount <= 50e8:
            amount_category = 4
        else:
            amount_category = 5

        log_prtcpt = np.log1p(expected_participants)

        if expected_participants <= 5:
            prtcpt_category = 0
        elif expected_participants <= 10:
            prtcpt_category = 1
        elif expected_participants <= 20:
            prtcpt_category = 2
        elif expected_participants <= 50:
            prtcpt_category = 3
        else:
            prtcpt_category = 4

        # 기관 빈도 (모든 유형 합산으로 근사)
        total_count = 0
        for type_stats in self.agency_bid_stats.values():
            stat = type_stats.get(agency_name)
            if stat:
                total_count += stat.get('bid_count', 0)
        log_agency_freq = np.log1p(max(total_count, 1))

        # features 순서: log_estimated_price, amount_category,
        #   year, month, dayofweek, log_prtcpt, prtcpt_category, log_agency_freq
        return [
            log_estimated_price,
            amount_category,
            bid_date.year,
            bid_date.month,
            bid_date.weekday(),
            log_prtcpt,
            prtcpt_category,
            log_agency_freq,
        ]

    def _get_agency_stat(self, bid_type: str, agency_name: str) -> Optional[Dict]:
        """기관별 통계 조회"""
        type_stats = self.agency_bid_stats.get(bid_type, {})
        stat = type_stats.get(agency_name)
        if stat:
            return {
                "agency_name": agency_name,
                "avg_rate": round(stat['avg_rate'], 2),
                "median_rate": round(stat['median_rate'], 2),
                "std_rate": round(stat.get('std_rate', 0) or 0, 2),
                "avg_participants": round(stat.get('avg_prtcpt', 0) or 0, 1),
                "bid_count": int(stat['bid_count']),
            }
        return None

    def _calc_confidence(
        self, bid_type: str, amount: float, participants: int,
        agency_stat: Optional[Dict]
    ) -> str:
        """예측 신뢰도 계산"""
        score = 0

        # 일반적 금액 범위
        if 1e7 <= amount <= 1e9:
            score += 2
        elif 1e6 <= amount <= 1e10:
            score += 1

        # 참여업체수 범위
        if 2 <= participants <= 50:
            score += 1

        # 기관 과거 데이터 존재
        if agency_stat and agency_stat.get('bid_count', 0) >= 50:
            score += 2
        elif agency_stat:
            score += 1

        if score >= 5:
            return "high"
        elif score >= 3:
            return "medium"
        return "low"

    def get_agency_statistics(
        self,
        bid_type: str,
        agency_name: str = "",
        keyword: str = "",
        limit: int = 20,
    ) -> Dict[str, Any]:
        """
        기관별 낙찰률 통계 조회

        Args:
            bid_type: 입찰 유형
            agency_name: 특정 기관명 (정확 매칭)
            keyword: 기관명 검색 키워드
            limit: 결과 수 제한
        """
        type_stats = self.agency_bid_stats.get(bid_type, {})

        if agency_name:
            stat = type_stats.get(agency_name)
            if stat:
                return {
                    "agencies": [self._format_agency_stat(agency_name, stat)],
                    "total": 1,
                }
            return {"agencies": [], "total": 0}

        # 키워드 검색
        results = []
        for name, stat in type_stats.items():
            if keyword and keyword not in name:
                continue
            results.append(self._format_agency_stat(name, stat))

        # 건수 내림차순 정렬
        results.sort(key=lambda x: -x['bid_count'])

        return {
            "agencies": results[:limit],
            "total": len(results),
        }

    def _format_agency_stat(self, name: str, stat: dict) -> dict:
        """기관 통계 포맷"""
        return {
            "agency_name": name,
            "avg_rate": round(stat['avg_rate'], 2),
            "median_rate": round(stat['median_rate'], 2),
            "std_rate": round(stat.get('std_rate', 0) or 0, 2),
            "avg_participants": round(stat.get('avg_prtcpt', 0) or 0, 1),
            "bid_count": int(stat['bid_count']),
        }

    def get_all_type_summary(self) -> Dict[str, Any]:
        """전체 유형별 요약"""
        summary = {}
        for bid_type, metric in self.metrics.items():
            type_stats = self.agency_bid_stats.get(bid_type, {})
            summary[bid_type] = {
                "model_mae": round(metric['mae'], 2),
                "model_r2": round(metric['r2'], 4),
                "total_agencies": len(type_stats),
            }
        return summary


# 싱글톤
_service: Optional[BidRatePredictionService] = None


def get_bidrate_prediction_service() -> BidRatePredictionService:
    """낙찰률 예측 서비스 인스턴스 반환"""
    global _service
    if _service is None:
        _service = BidRatePredictionService()
    return _service
