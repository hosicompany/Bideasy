#!/usr/bin/env python
"""
예측 서비스 테스트 스크립트
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.prediction_service import PredictionService

print("=" * 60)
print("Bid Easy - Prediction Service Test")
print("=" * 60)

# 서비스 초기화
print("\n[1] Loading model...")
service = PredictionService()
print("  Model loaded successfully!")
print(f"  Model metrics: MAE={service.metrics['mae']:.2f}%, R2={service.metrics['r2']:.4f}")

# 테스트 케이스
print("\n[2] Running predictions...")

test_cases = [
    {"bid_type": "construction", "amount": 100_000_000, "participants": 15},
    {"bid_type": "construction", "amount": 500_000_000, "participants": 30},
    {"bid_type": "goods", "amount": 50_000_000, "participants": 10},
    {"bid_type": "goods", "amount": 10_000_000, "participants": 5},
    {"bid_type": "service", "amount": 200_000_000, "participants": 20},
    {"bid_type": "service", "amount": 30_000_000, "participants": 8},
]

print("\n" + "-" * 60)
print(f"{'Type':<15} {'Amount':>15} {'Participants':>12} {'Predicted':>12} {'Confidence':<10}")
print("-" * 60)

for case in test_cases:
    result = service.predict(
        bid_type=case["bid_type"],
        amount=case["amount"],
        expected_participants=case["participants"]
    )
    
    amount_str = f"{case['amount']/1e8:.1f}억" if case['amount'] >= 1e8 else f"{case['amount']/1e7:.0f}천만"
    
    print(f"{case['bid_type']:<15} {amount_str:>15} {case['participants']:>12} "
          f"{result['predicted_rate']:>10.2f}% {result['confidence']:<10}")

print("-" * 60)

# 통계 정보
print("\n[3] Statistics by type:")
stats = service.get_statistics()
for bid_type, stat in stats.items():
    print(f"  [{bid_type}] avg: {stat['avg_rate']:.2f}%, median: {stat['median_rate']:.2f}%")

print("\n" + "=" * 60)
print("Test completed!")
print("=" * 60)
