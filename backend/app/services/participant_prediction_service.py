"""
참여업체수 예측 서비스
- 입찰 공고 정보를 기반으로 예상 참여업체수 예측
- 블루오션 탐지 및 경쟁 강도 분류
- 참여수 기반 적응형 투찰 전략 추천
"""

import joblib
import numpy as np
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime, date
import logging

logger = logging.getLogger(__name__)


# 참여수 구간 정의
PRTCPT_BUCKETS = {
    0: {"label": "블루오션", "range": "1-5명", "color": "blue", "emoji": "🔵"},
    1: {"label": "적정 경쟁", "range": "6-10명", "color": "green", "emoji": "🟢"},
    2: {"label": "보통", "range": "11-20명", "color": "yellow", "emoji": "🟡"},
    3: {"label": "경쟁 치열", "range": "21-50명", "color": "orange", "emoji": "🟠"},
    4: {"label": "레드오션", "range": "51명 이상", "color": "red", "emoji": "🔴"},
}

# 참여수별 추천 투찰 전략 (낙찰하한율 대비 마진 %)
# 백테스트 검증 결과: 하한율에 가까울수록 항상 유리
# → 마진은 동가(추첨) 회피용 최소값만 적용
# → 참여수 예측의 진짜 가치는 "참여 여부 판단"(블루오션 선별)
DYNAMIC_MARGINS = {
    0: {"margin": 0.01, "desc": "블루오션! 적극 참여 추천 (낙찰 확률 높음)"},
    1: {"margin": 0.01, "desc": "적정 경쟁, 참여 추천"},
    2: {"margin": 0.01, "desc": "보통 경쟁, 참여 가능"},
    3: {"margin": 0.01, "desc": "치열한 경쟁, 신중히 판단"},
    4: {"margin": 0.00, "desc": "로또 구간, 참여 비추천 (동가추첨 확률 높음)"},
}


class ParticipantPredictionService:
    """참여업체수 예측 서비스"""

    BID_TYPES = {
        "goods": 1,
        "service": 2,
        "construction": 0,
    }

    def __init__(self, model_path: Optional[Path] = None):
        if model_path is None:
            model_path = Path(__file__).parent.parent.parent / "models" / "participant_predictor.joblib"

        self.model_path = model_path
        self.reg_model = None
        self.cls_model = None
        self.agency_stats = {}
        self.agency_counts = {}
        self.global_avg_prtcpt = 30.0
        self.metrics = {}

        self._load_model()

    def _load_model(self):
        """모델 로드"""
        try:
            data = joblib.load(self.model_path)
            self.reg_model = data['reg_model']
            self.cls_model = data['cls_model']
            self.agency_stats = data.get('agency_stats', {})
            self.agency_counts = data.get('agency_counts', {})
            self.global_avg_prtcpt = data.get('global_avg_prtcpt', 30.0)
            self.metrics = data.get('metrics', {})
            logger.info(f"참여수 예측 모델 로드 완료: {self.model_path}")
        except Exception as e:
            logger.error(f"참여수 예측 모델 로드 실패: {e}")
            raise

    def predict(
        self,
        bid_type: str,
        estimated_amount: float,
        agency_name: str = "",
        bid_date: Optional[date] = None,
    ) -> Dict[str, Any]:
        """
        참여업체수 예측

        Args:
            bid_type: 입찰 유형 (construction, goods, service)
            estimated_amount: 추정 금액
            agency_name: 발주기관명
            bid_date: 입찰일

        Returns:
            예측 결과 (예상 참여수, 구간, 추천 전략)
        """
        if self.cls_model is None:
            raise RuntimeError("모델이 로드되지 않았습니다.")

        if bid_date is None:
            bid_date = date.today()

        # 특성 생성
        features = self._create_features(
            bid_type=bid_type,
            estimated_amount=estimated_amount,
            agency_name=agency_name,
            bid_date=bid_date,
        )

        # 회귀 예측 (참여수)
        predicted_count = max(1, int(round(self.reg_model.predict([features])[0])))

        # 분류 예측 (구간)
        predicted_bucket = int(self.cls_model.predict([features])[0])
        bucket_proba = self.cls_model.predict_proba([features])[0]

        # 블루오션 확률 (구간 0 + 구간 1)
        blue_ocean_prob = float(bucket_proba[0] + bucket_proba[1]) if len(bucket_proba) > 1 else float(bucket_proba[0])

        # 레드오션 확률 (구간 4)
        red_ocean_prob = float(bucket_proba[4]) if len(bucket_proba) > 4 else 0.0

        # 추천 전략
        strategy = DYNAMIC_MARGINS[predicted_bucket]
        bucket_info = PRTCPT_BUCKETS[predicted_bucket]

        # 기관 통계
        agency_stat = self.agency_stats.get(agency_name, None)

        return {
            "predicted_count": predicted_count,
            "predicted_bucket": predicted_bucket,
            "bucket_info": bucket_info,
            "probabilities": {
                bk["range"]: round(float(bucket_proba[i]), 3)
                for i, bk in PRTCPT_BUCKETS.items()
                if i < len(bucket_proba)
            },
            "blue_ocean_probability": round(blue_ocean_prob, 3),
            "red_ocean_probability": round(red_ocean_prob, 3),
            "is_blue_ocean": blue_ocean_prob > 0.5,
            "competition_level": bucket_info["label"],
            "strategy": {
                "recommended_margin": strategy["margin"],
                "description": strategy["desc"],
            },
            "agency_history": {
                "avg_participants": round(agency_stat["avg_prtcpt"], 1) if agency_stat else None,
                "total_bids": int(agency_stat["bid_count"]) if agency_stat else None,
                "median_participants": round(agency_stat["median_prtcpt"], 1) if agency_stat else None,
            } if agency_stat else None,
            "model_accuracy": {
                "bucket_accuracy": round(self.metrics.get("classification", {}).get("accuracy", 0), 3),
                "blue_ocean_accuracy": round(self.metrics.get("classification", {}).get("binary_accuracy", 0), 3),
            },
        }

    def _create_features(
        self,
        bid_type: str,
        estimated_amount: float,
        agency_name: str,
        bid_date: date,
    ) -> list:
        """예측을 위한 특성 벡터 생성"""
        bid_type_encoded = self.BID_TYPES.get(bid_type, 0)
        log_estimated_price = np.log1p(estimated_amount)

        # 금액 카테고리
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

        # 기관 빈도
        agency_freq = self.agency_counts.get(agency_name, 1)
        log_agency_freq = np.log1p(agency_freq)

        # 기관 평균 참여수
        agency_stat = self.agency_stats.get(agency_name, None)
        avg_prtcpt = agency_stat["avg_prtcpt"] if agency_stat else self.global_avg_prtcpt
        log_agency_avg_prtcpt = np.log1p(avg_prtcpt)

        return [
            bid_type_encoded,
            log_estimated_price,
            amount_category,
            bid_date.year,
            bid_date.month,
            bid_date.weekday(),
            (bid_date.month - 1) // 3 + 1,  # quarter
            log_agency_freq,
            log_agency_avg_prtcpt,
        ]

    def get_agency_stats(self, agency_name: str) -> Optional[Dict[str, Any]]:
        """특정 기관의 과거 통계 조회"""
        stat = self.agency_stats.get(agency_name)
        if stat:
            return {
                "agency_name": agency_name,
                "avg_participants": round(stat["avg_prtcpt"], 1),
                "median_participants": round(stat["median_prtcpt"], 1),
                "total_bids": int(stat["bid_count"]),
            }
        return None

    def search_agencies(self, keyword: str, limit: int = 10) -> list:
        """기관명 검색"""
        results = []
        for name, stat in self.agency_stats.items():
            if keyword in name:
                results.append({
                    "agency_name": name,
                    "avg_participants": round(stat["avg_prtcpt"], 1),
                    "total_bids": int(stat["bid_count"]),
                })
        results.sort(key=lambda x: -x["total_bids"])
        return results[:limit]


# 싱글톤
_service: Optional[ParticipantPredictionService] = None


def get_participant_prediction_service() -> ParticipantPredictionService:
    """참여수 예측 서비스 인스턴스 반환"""
    global _service
    if _service is None:
        _service = ParticipantPredictionService()
    return _service
