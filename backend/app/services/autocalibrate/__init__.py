"""
BidEasy 자가보정 입찰가 알고리즘 패키지
=========================================
입찰 결과 피드백 기반으로 입찰가 산정 파라미터(BID_STRATEGY)를
자동·지속·폐쇄 루프로 재최적화한다.

## 모듈 구성
- strategy_store : 버전 관리 파라미터 저장소 (정적 BID_STRATEGY 대체)
- dataset        : 데이터 적재·정제 (BidRecord, fingerprint)
- risk_model     : 하한선 탈락 위험 해석적 모델링 (신규성 핵심)
- optimizer      : 위험제약 최적화 + 적응형 시간 가중
- guard          : regression 가드 (다지표·walk-forward·세그먼트 안전성)
- loop           : 폐쇄 루프 오케스트레이터

## 공개 API
- get_default_store()       : 전략 파라미터 버전 관리 저장소
- run_calibration_cycle()   : 자가보정 사이클 1회 실행

## 향후 4번 확장 포인트 (ML / 블루오션 의사결정)
- StrategyStore(ABC)        : FileStrategyStore → DbStrategyStore 승격 (Alembic 마이그레이션만)
- risk_model.dropout_probability : 해석적 모델 → 학습된 ML 모델로 교체 가능 (인터페이스 고정)
- optimizer.CandidateParams.features : 블루오션 의사결정 신호(참여수 예측 등) 추가 슬롯
"""

from app.services.autocalibrate.loop import CycleReport, run_calibration_cycle
from app.services.autocalibrate.strategy_store import (
    FileStrategyStore,
    StrategyStore,
    StrategyVersion,
    get_default_store,
    make_version_id,
)

__all__ = [
    "FileStrategyStore",
    "StrategyStore",
    "StrategyVersion",
    "CycleReport",
    "get_default_store",
    "make_version_id",
    "run_calibration_cycle",
]
