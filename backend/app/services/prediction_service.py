"""
낙찰률 예측 서비스
- 학습된 ML 모델을 사용하여 낙찰률 예측
"""

import joblib
import numpy as np
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class PredictionService:
    """낙찰률 예측 서비스"""
    
    # 입찰 유형 매핑
    BID_TYPES = {
        "goods": 1,
        "service": 2,
        "construction": 0,
    }
    
    def __init__(self, model_path: Optional[Path] = None):
        """
        Args:
            model_path: 모델 파일 경로 (기본값: models/bid_rate_predictor.joblib)
        """
        if model_path is None:
            model_path = Path(__file__).parent.parent.parent / "models" / "bid_rate_predictor.joblib"
        
        self.model_path = model_path
        self.model = None
        self.label_encoder = None
        self.features = None
        self.metrics = None
        
        self._load_model()
    
    def _load_model(self):
        """모델 로드"""
        try:
            data = joblib.load(self.model_path)
            self.model = data['model']
            self.label_encoder = data['label_encoder']
            self.features = data['features']
            self.metrics = data['metrics']
            logger.info(f"모델 로드 완료: {self.model_path}")
        except Exception as e:
            logger.error(f"모델 로드 실패: {e}")
            raise
    
    def predict(
        self,
        bid_type: str,
        amount: float,
        expected_participants: int = 10,
        target_date: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """
        낙찰률 예측
        
        Args:
            bid_type: 입찰 유형 (goods, service, construction)
            amount: 예상 입찰 금액
            expected_participants: 예상 참여업체수
            target_date: 목표 일자 (기본값: 현재)
            
        Returns:
            예측 결과 딕셔너리
        """
        if self.model is None:
            raise RuntimeError("모델이 로드되지 않았습니다.")
        
        # 입력 검증
        if bid_type not in self.BID_TYPES:
            raise ValueError(f"지원하지 않는 입찰 유형: {bid_type}")
        
        if amount <= 0:
            raise ValueError("금액은 0보다 커야 합니다.")
        
        if expected_participants < 1:
            expected_participants = 1
        
        # 날짜 설정
        if target_date is None:
            target_date = datetime.now()
        
        # 특성 생성
        features = self._create_features(
            bid_type=bid_type,
            amount=amount,
            expected_participants=expected_participants,
            target_date=target_date
        )
        
        # 예측
        predicted_rate = self.model.predict([features])[0]
        
        # 범위 제한 (0-100%)
        predicted_rate = max(0, min(100, predicted_rate))
        
        # 신뢰구간 계산 (MAE 기반)
        mae = self.metrics.get('mae', 3.0)
        lower_bound = max(0, predicted_rate - mae * 1.5)
        upper_bound = min(100, predicted_rate + mae * 1.5)
        
        # 신뢰도 판단
        confidence = self._calculate_confidence(
            amount=amount,
            participants=expected_participants
        )
        
        return {
            "predicted_rate": round(predicted_rate, 2),
            "confidence": confidence,
            "range": {
                "lower": round(lower_bound, 2),
                "upper": round(upper_bound, 2)
            },
            "input": {
                "bid_type": bid_type,
                "amount": amount,
                "expected_participants": expected_participants,
                "target_date": target_date.isoformat()
            },
            "model_metrics": {
                "mae": round(self.metrics.get('mae', 0), 2),
                "r2": round(self.metrics.get('r2', 0), 4)
            }
        }
    
    def _create_features(
        self,
        bid_type: str,
        amount: float,
        expected_participants: int,
        target_date: datetime
    ) -> list:
        """예측을 위한 특성 벡터 생성"""
        
        # bid_type_encoded
        bid_type_encoded = self.BID_TYPES.get(bid_type, 0)
        
        # log_amount
        log_amount = np.log1p(amount)
        
        # amount_category (0-5)
        if amount <= 1e7:
            amount_category = 0
        elif amount <= 5e7:
            amount_category = 1
        elif amount <= 1e8:
            amount_category = 2
        elif amount <= 5e8:
            amount_category = 3
        elif amount <= 1e9:
            amount_category = 4
        else:
            amount_category = 5
        
        # 날짜 특성
        year = target_date.year
        month = target_date.month
        dayofweek = target_date.weekday()
        
        # prtcpt_category (참여업체수 카테고리)
        if expected_participants <= 2:
            prtcpt_category = 0
        elif expected_participants <= 5:
            prtcpt_category = 1
        elif expected_participants <= 10:
            prtcpt_category = 2
        elif expected_participants <= 20:
            prtcpt_category = 3
        elif expected_participants <= 50:
            prtcpt_category = 4
        else:
            prtcpt_category = 5
        
        # features 순서: ['bid_type_encoded', 'log_amount', 'amount_category', 
        #                'year', 'month', 'dayofweek', 'prtcpt_category']
        return [
            bid_type_encoded,
            log_amount,
            amount_category,
            year,
            month,
            dayofweek,
            prtcpt_category
        ]
    
    def _calculate_confidence(
        self,
        amount: float,
        participants: int
    ) -> str:
        """신뢰도 계산"""
        # 일반적인 범위 내의 데이터일수록 신뢰도 높음
        score = 0
        
        # 금액 범위 체크 (1천만 ~ 10억)
        if 1e7 <= amount <= 1e9:
            score += 2
        elif 1e6 <= amount <= 1e10:
            score += 1
        
        # 참여업체수 범위 체크 (2 ~ 50)
        if 2 <= participants <= 50:
            score += 2
        elif 1 <= participants <= 100:
            score += 1
        
        if score >= 4:
            return "high"
        elif score >= 2:
            return "medium"
        else:
            return "low"
    
    def get_statistics(self, bid_type: Optional[str] = None) -> Dict[str, Any]:
        """유형별 통계 정보 반환"""
        # 일반적인 낙찰률 범위 (학습 데이터 기반)
        stats = {
            "goods": {
                "avg_rate": 90.96,
                "median_rate": 90.01,
                "typical_range": [85, 95]
            },
            "service": {
                "avg_rate": 89.79,
                "median_rate": 88.25,
                "typical_range": [83, 95]
            },
            "construction": {
                "avg_rate": 88.16,
                "median_rate": 87.91,
                "typical_range": [82, 93]
            }
        }
        
        if bid_type:
            return stats.get(bid_type, {})
        return stats


# 싱글톤 인스턴스
_prediction_service: Optional[PredictionService] = None


def get_prediction_service() -> PredictionService:
    """예측 서비스 인스턴스 반환"""
    global _prediction_service
    if _prediction_service is None:
        _prediction_service = PredictionService()
    return _prediction_service
