"""
예측 기능 테스트 스크립트
"""

import sys
sys.path.insert(0, '.')

from app.services.prediction_service import get_prediction_service, BidType

def test_prediction():
    """예측 기능 테스트"""
    print("=" * 50)
    print("BidEasy 예측 기능 테스트")
    print("=" * 50)
    
    service = get_prediction_service()
    
    # 테스트 케이스들
    test_cases = [
        {"base_price": 50_000_000, "bid_type": BidType.GOODS, "desc": "물품 5천만원"},
        {"base_price": 100_000_000, "bid_type": BidType.GOODS, "desc": "물품 1억"},
        {"base_price": 500_000_000, "bid_type": BidType.SERVICE, "desc": "용역 5억"},
        {"base_price": 1_000_000_000, "bid_type": BidType.CONSTRUCTION, "desc": "공사 10억"},
        {"base_price": 10_000_000_000, "bid_type": BidType.CONSTRUCTION, "desc": "공사 100억"},
    ]
    
    for case in test_cases:
        print(f"\n📊 테스트: {case['desc']}")
        print("-" * 40)
        
        result = service.predict(
            base_price=case["base_price"],
            bid_type=case["bid_type"]
        )
        
        print(f"기초금액: {case['base_price']:,}원")
        print(f"입찰유형: {case['bid_type'].value}")
        print("\n🎯 예측 결과:")
        print(f"  - 사정률 구간: {result.min_rate}% ~ {result.max_rate}%")
        print(f"  - 추천 사정률: {result.recommended_rate}%")
        print(f"  - 추천 투찰가: {result.recommended_price:,}원")
        print(f"  - 신뢰도: {result.confidence_level} ({result.confidence})")
        print("\n📝 분석 근거:")
        for basis in result.analysis_basis:
            print(f"  • {basis}")
    
    print("\n" + "=" * 50)
    print("✅ 예측 기능 테스트 완료!")
    print("=" * 50)


def test_backtest():
    """백테스트 기능 테스트"""
    print("\n" + "=" * 50)
    print("백테스트 기능 테스트")
    print("=" * 50)
    
    service = get_prediction_service()
    
    # 가상 테스트 데이터
    test_data = [
        {"base_price": 100_000_000, "actual_winning_rate": 87.5},
        {"base_price": 50_000_000, "actual_winning_rate": 88.2},
        {"base_price": 200_000_000, "actual_winning_rate": 86.8},
        {"base_price": 80_000_000, "actual_winning_rate": 87.0},
        {"base_price": 150_000_000, "actual_winning_rate": 85.5},
    ]
    
    result = service.backtest(test_data, BidType.GOODS)
    
    print("\n📊 백테스트 결과:")
    print(f"  - 총 테스트 건수: {result['total']}건")
    print(f"  - 구간 적중: {result['hits']}건")
    print(f"  - 구간 미적중: {result['misses']}건")
    print(f"  - 적중률: {result['hit_rate']}%")
    print(f"  - 평균 오차: {result['avg_error']}%")
    
    print("\n✅ 백테스트 테스트 완료!")


if __name__ == "__main__":
    test_prediction()
    test_backtest()
