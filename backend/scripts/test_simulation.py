#!/usr/bin/env python
"""
시뮬레이션 서비스 테스트 스크립트
"""

import sys
from pathlib import Path
from datetime import date
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.simulation_service import (
    BidSimulationService, 
    AgencyType
)

print("=" * 70)
print("Bid Easy - Monte Carlo Simulation Test")
print("=" * 70)

service = BidSimulationService()

# 테스트 케이스: 1억원 공사
base_amount = 100_000_000
a_value = 15_000_000  # A값 1,500만원

print("\n[Test Case]")
print(f"  Base Amount: {base_amount:,}원")
print(f"  A-Value: {a_value:,}원")
print("  Bid Type: construction")

# 1. 몬테카를로 시뮬레이션
print("\n[1] Monte Carlo Simulation (10,000 runs)")
dist = service.run_monte_carlo(
    base_amount=base_amount,
    agency_type=AgencyType.NATIONAL,
    num_simulations=10000
)

print("  Expected Planned Price:")
print(f"    Mean: {dist['mean']:,.0f}원")
print(f"    Std: {dist['std']:,.0f}원")
print(f"    Range (5-95%): {dist['percentile_5']:,.0f} ~ {dist['percentile_95']:,.0f}원")

# 2. 낙찰하한율 확인
print("\n[2] Lower Limit Check")
limit_old = service.get_lower_limit("construction", base_amount, date(2026, 1, 29))
limit_new = service.get_lower_limit("construction", base_amount, date(2026, 1, 30))
print(f"  Before 2026.1.30: {limit_old * 100:.3f}%")
print(f"  After 2026.1.30: {limit_new * 100:.3f}%")

# 3. 최적 투찰가 계산
print("\n[3] Optimal Bid Calculation")
result = service.calculate_optimal_bid(
    base_amount=base_amount,
    a_value=a_value,
    bid_type="construction",
    bid_date=date(2026, 2, 15)
)

print(f"  Lower Limit: {result['lower_limit_pct']}")
print(f"  Optimal Bid: {result['optimal_bid']:,.0f}원")
print(f"  Bid Rate at Mean: {result['bid_rate']['at_mean']:.3f}%")
print(f"  Tie Risk: {result['tie_risk']}")
print(f"  Danger Zone: {result['danger_zone']:,.0f}원")
print(f"\n  >> {result['recommendation']}")

# 4. 다양한 케이스 테스트
print("\n[4] Various Cases")
print("-" * 70)
print(f"{'Type':<12} {'Base':>12} {'A-Value':>12} {'Optimal':>15} {'Rate':>8}")
print("-" * 70)

cases = [
    ("construction", 500_000_000, 50_000_000),
    ("construction", 50_000_000, 5_000_000),
    ("goods", 100_000_000, 0),
    ("goods", 50_000_000, 0),
    ("service", 200_000_000, 0),
]

for bid_type, base, a_val in cases:
    r = service.calculate_optimal_bid(
        base_amount=base,
        a_value=a_val,
        bid_type=bid_type,
        bid_date=date(2026, 2, 15)
    )
    base_str = f"{base/1e8:.1f}억" if base >= 1e8 else f"{base/1e7:.0f}천만"
    a_str = f"{a_val/1e7:.0f}천만" if a_val > 0 else "-"
    print(f"{bid_type:<12} {base_str:>12} {a_str:>12} {r['optimal_bid']:>15,.0f} {r['bid_rate']['at_mean']:>7.2f}%")

print("-" * 70)

print("\n" + "=" * 70)
print("Test completed!")
print("=" * 70)
