#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
BidEasy 스마트 투찰 백테스트
- 기존 고정 마진 전략 vs 참여수 적응형 전략 비교
- 143만건 실제 낙찰 데이터 기반

전략 비교:
  1. 고정 전략: 항상 하한율 +0.01%
  2. 스마트 전략: 참여수에 따라 마진 자동 조절
     - 1-5명: +0.50%  (분산 큰 블루오션)
     - 6-10명: +0.10%
     - 11-20명: +0.05%
     - 21-50명: +0.01%
     - 51+명: +0.00%  (로또 구간)
"""

import sqlite3
import json
import numpy as np
from pathlib import Path
from datetime import date, datetime
from collections import defaultdict
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# 낙찰하한율 (구제도)
LOWER_LIMITS = {
    "construction": [
        (10_000_000_000, 0.85495),
        (5_000_000_000, 0.85495),
        (1_000_000_000, 0.86745),
        (300_000_000, 0.87745),
        (0, 0.87745),
    ],
    "goods": 0.84245,
    "service": 0.87745,
}

# 참여수별 동적 마진 (%)
DYNAMIC_MARGINS = {
    "1-5": 0.50,
    "6-10": 0.10,
    "11-20": 0.05,
    "21-50": 0.01,
    "51+": 0.00,
}


def get_lower_limit(bid_type, estimated_amount):
    if bid_type == "construction":
        for threshold, rate in LOWER_LIMITS["construction"]:
            if estimated_amount >= threshold:
                return rate
        return LOWER_LIMITS["construction"][-1][1]
    elif bid_type == "goods":
        return LOWER_LIMITS["goods"]
    elif bid_type == "service":
        return LOWER_LIMITS["service"]
    return 0.87745


def get_prtcpt_bucket(prtcpt):
    if prtcpt <= 5: return "1-5"
    elif prtcpt <= 10: return "6-10"
    elif prtcpt <= 20: return "11-20"
    elif prtcpt <= 50: return "21-50"
    else: return "51+"


def run_backtest():
    base_dir = Path(__file__).parent.parent
    db_path = base_dir / "data" / "historical" / "bid_results_5years.db"

    print("=" * 70)
    print("BidEasy 스마트 투찰 백테스트")
    print("고정 마진 vs 참여수 적응형 마진 비교")
    print("=" * 70)

    conn = sqlite3.connect(str(db_path))

    strategies = {
        "고정 +0.01%": lambda bucket: 0.01,
        "스마트 (적응형)": lambda bucket: DYNAMIC_MARGINS[bucket],
    }

    for bid_type in ["construction", "goods", "service"]:
        type_name = {"construction": "공사", "goods": "물품", "service": "용역"}[bid_type]
        print(f"\n{'=' * 70}")
        print(f"[{type_name}] 백테스트")
        print("=" * 70)

        cursor = conn.execute(f"""
            SELECT sucsfbid_amt, sucsfbid_rate, data_json
            FROM bid_results
            WHERE bid_type = '{bid_type}'
            AND sucsfbid_rate > 50 AND sucsfbid_rate <= 100
            AND sucsfbid_amt > 10000
        """)

        rows = cursor.fetchall()
        total = len(rows)
        print(f"  테스트 데이터: {total:,}건\n")

        if total == 0:
            continue

        # 결과 저장
        results = {name: {"win": 0, "tie": 0, "lose": 0, "disq": 0}
                   for name in strategies}

        # 참여수 구간별 추적
        bucket_results = {
            name: {b: {"win": 0, "tie": 0, "lose": 0, "total": 0}
                   for b in ["1-5", "6-10", "11-20", "21-50", "51+"]}
            for name in strategies
        }
        bucket_totals = defaultdict(int)

        for sucsfbid_amt, sucsfbid_rate, data_json in rows:
            planned_price = sucsfbid_amt / (sucsfbid_rate / 100.0)

            try:
                data = json.loads(data_json)
                prtcpt = int(data.get("prtcptCnum", 0) or 0)
            except:
                prtcpt = 0

            if prtcpt == 0:
                continue

            bucket = get_prtcpt_bucket(prtcpt)
            bucket_totals[bucket] += 1

            lower_limit_pct = get_lower_limit(bid_type, planned_price) * 100

            for strategy_name, margin_fn in strategies.items():
                margin = margin_fn(bucket)
                our_rate = lower_limit_pct + margin

                if our_rate > 100 or our_rate < lower_limit_pct:
                    results[strategy_name]["disq"] += 1
                    continue

                if our_rate < sucsfbid_rate:
                    results[strategy_name]["win"] += 1
                    bucket_results[strategy_name][bucket]["win"] += 1
                elif abs(our_rate - sucsfbid_rate) < 0.001:
                    results[strategy_name]["tie"] += 1
                else:
                    results[strategy_name]["lose"] += 1

                bucket_results[strategy_name][bucket]["total"] += 1

        # 전체 결과
        print(f"  {'전략':<20} {'낙찰':>8} {'동가':>8} {'탈락':>8} {'낙찰률':>10}")
        print("  " + "-" * 58)

        for name in strategies:
            r = results[name]
            valid = r["win"] + r["tie"] + r["lose"]
            win_rate = r["win"] / valid * 100 if valid > 0 else 0
            print(f"  {name:<20} {r['win']:>8,} {r['tie']:>8,} {r['lose']:>8,} {win_rate:>9.1f}%")

        # 참여수 구간별 상세 비교
        print(f"\n  참여수 구간별 낙찰률 비교:")
        print(f"  {'구간':>6} {'건수':>8}  {'고정+0.01%':>12}  {'스마트(적응형)':>14}  {'차이':>8}")
        print("  " + "-" * 56)

        total_fixed_wins = 0
        total_smart_wins = 0
        total_valid = 0

        for bucket in ["1-5", "6-10", "11-20", "21-50", "51+"]:
            bt = bucket_totals[bucket]
            if bt == 0:
                continue

            fixed_r = bucket_results["고정 +0.01%"][bucket]
            smart_r = bucket_results["스마트 (적응형)"][bucket]

            fixed_rate = fixed_r["win"] / fixed_r["total"] * 100 if fixed_r["total"] > 0 else 0
            smart_rate = smart_r["win"] / smart_r["total"] * 100 if smart_r["total"] > 0 else 0
            diff = smart_rate - fixed_rate

            total_fixed_wins += fixed_r["win"]
            total_smart_wins += smart_r["win"]
            total_valid += fixed_r["total"]

            diff_str = f"+{diff:.1f}%" if diff > 0 else f"{diff:.1f}%"
            print(f"  {bucket:>5}명 {bt:>8,}  {fixed_rate:>11.1f}%  {smart_rate:>13.1f}%  {diff_str:>8}")

        if total_valid > 0:
            overall_fixed = total_fixed_wins / total_valid * 100
            overall_smart = total_smart_wins / total_valid * 100
            overall_diff = overall_smart - overall_fixed
            diff_str = f"+{overall_diff:.1f}%" if overall_diff > 0 else f"{overall_diff:.1f}%"
            print("  " + "-" * 56)
            print(f"  {'전체':>6} {total_valid:>8,}  {overall_fixed:>11.1f}%  {overall_smart:>13.1f}%  {diff_str:>8}")

    conn.close()
    print(f"\n{'=' * 70}")
    print("백테스트 완료!")
    print("=" * 70)
    print("""
[해석]
- '고정 +0.01%': 모든 입찰에 하한율 + 0.01% 고정 투찰
- '스마트 (적응형)': 참여수에 따라 마진 자동 조절
  → 소수 참여(1-5명)에서는 높은 마진, 다수 참여(51+)에서는 하한율 정확히

※ 스마트 전략의 진짜 가치는 '어디에 참여할지'를 고르는 것.
   여기서는 동일 입찰에서의 전략 차이만 비교합니다.
""")


if __name__ == "__main__":
    run_backtest()
