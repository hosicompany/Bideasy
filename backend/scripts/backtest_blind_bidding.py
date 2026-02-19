#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
BidEasy 모의 투찰 백테스트
- 답안지(예정가격) 없이 투찰했을 때의 낙찰 성공률 검증
- 143만건 실제 낙찰 데이터 기반

전략:
  "낙찰하한율 + 소폭 마진" 으로 투찰 → 실제 낙찰자보다 예정가격에 더 가까운가?

판정 기준:
  - 실제 낙찰률(actual_rate) > 우리 투찰률(our_rate) >= 낙찰하한율
    → 우리가 낙찰자보다 하한율에 더 가까우므로 "우리가 낙찰"
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

# ============================================================
# 낙찰하한율 테이블 (2026.1.30 전후 구분)
# ============================================================

LOWER_LIMITS_2026 = {
    "construction": [
        (10_000_000_000, 0.87495),  # 100억 이상
        (5_000_000_000, 0.87495),   # 50억~100억
        (1_000_000_000, 0.88745),   # 10억~50억
        (300_000_000, 0.89745),     # 3억~10억
        (0, 0.89745),              # 3억 미만
    ],
    "goods": 0.84245,    # 물품 일반 (2.1억 미만 기준)
    "service": 0.87995,  # 용역 일반
}

LOWER_LIMITS_OLD = {
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

CUTOFF_DATE = date(2026, 1, 30)


def get_lower_limit(bid_type: str, estimated_amount: float, bid_date: date) -> float:
    """낙찰하한율 조회"""
    limits = LOWER_LIMITS_2026 if bid_date >= CUTOFF_DATE else LOWER_LIMITS_OLD

    if bid_type == "construction":
        for threshold, rate in limits["construction"]:
            if estimated_amount >= threshold:
                return rate
        return limits["construction"][-1][1]
    elif bid_type == "goods":
        return limits["goods"]
    elif bid_type == "service":
        return limits["service"]
    return 0.87745


# ============================================================
# 백테스트 메인
# ============================================================

def run_backtest():
    base_dir = Path(__file__).parent.parent
    db_path = base_dir / "data" / "historical" / "bid_results_5years.db"

    print("=" * 70)
    print("BidEasy 모의 투찰 백테스트 (Blind Bidding)")
    print("=" * 70)
    print(f"DB: {db_path}")

    conn = sqlite3.connect(str(db_path))

    # 전략별 마진 설정 (낙찰하한율 + margin%)
    STRATEGIES = {
        "하한율 정확히": 0.000,
        "하한율 +0.01%": 0.010,
        "하한율 +0.05%": 0.050,
        "하한율 +0.10%": 0.100,
        "하한율 +0.20%": 0.200,
        "하한율 +0.50%": 0.500,
    }

    for bid_type in ["construction", "goods", "service"]:
        print(f"\n{'=' * 70}")
        type_name = {"construction": "공사", "goods": "물품", "service": "용역"}[bid_type]
        print(f"[{type_name}] 백테스트")
        print("=" * 70)

        # 데이터 로드 (낙찰률 유효 범위만)
        cursor = conn.execute(f"""
            SELECT sucsfbid_amt, sucsfbid_rate, data_json, openg_dt
            FROM bid_results
            WHERE bid_type = '{bid_type}'
            AND sucsfbid_rate > 50 AND sucsfbid_rate <= 100
            AND sucsfbid_amt > 10000
        """)

        rows = cursor.fetchall()
        total = len(rows)
        print(f"  테스트 데이터: {total:,}건")

        if total == 0:
            continue

        # 각 전략별 결과
        results = {name: {"win": 0, "tie": 0, "lose": 0, "disqualified": 0}
                   for name in STRATEGIES}

        # 연도별 추적
        yearly_wins = {name: defaultdict(int) for name in STRATEGIES}
        yearly_total = defaultdict(int)

        # 참여업체수별 추적
        participant_wins = {name: defaultdict(int) for name in STRATEGIES}
        participant_total = defaultdict(int)

        for sucsfbid_amt, sucsfbid_rate, data_json, openg_dt in rows:
            # 예정가격 역산
            planned_price = sucsfbid_amt / (sucsfbid_rate / 100.0)

            # 날짜 파싱
            try:
                data = json.loads(data_json)
                dt_str = data.get("rlOpengDt", "")
                if dt_str:
                    bid_date = datetime.strptime(dt_str[:10], "%Y-%m-%d").date()
                else:
                    bid_date = date(2024, 1, 1)  # 기본값
            except:
                bid_date = date(2024, 1, 1)

            # 참여업체수
            try:
                prtcpt = int(data.get("prtcptCnum", 0) or 0)
            except:
                prtcpt = 0

            # 연도
            year = bid_date.year

            # 낙찰하한율 조회
            lower_limit = get_lower_limit(bid_type, planned_price, bid_date)
            lower_limit_pct = lower_limit * 100  # ex: 87.745

            yearly_total[year] += 1

            prtcpt_bucket = "1-5" if prtcpt <= 5 else "6-10" if prtcpt <= 10 else "11-20" if prtcpt <= 20 else "21-50" if prtcpt <= 50 else "51+"
            participant_total[prtcpt_bucket] += 1

            for strategy_name, margin in STRATEGIES.items():
                our_rate = lower_limit_pct + margin

                if our_rate > 100:
                    results[strategy_name]["disqualified"] += 1
                    continue

                # 판정:
                # 실제 낙찰자의 투찰률 = sucsfbid_rate
                # 우리 투찰률 = our_rate
                # 낙찰 시스템: 하한율 이상 중 하한율에 가장 가까운 사람이 낙찰
                #
                # our_rate < sucsfbid_rate → 우리가 더 하한율에 가까움 → 우리 낙찰!
                # our_rate == sucsfbid_rate → 동가 (추첨)
                # our_rate > sucsfbid_rate → 실제 낙찰자가 더 가까움 → 우리 탈락

                if our_rate < lower_limit_pct:
                    results[strategy_name]["disqualified"] += 1
                elif our_rate < sucsfbid_rate:
                    results[strategy_name]["win"] += 1
                    yearly_wins[strategy_name][year] += 1
                    participant_wins[strategy_name][prtcpt_bucket] += 1
                elif abs(our_rate - sucsfbid_rate) < 0.001:
                    results[strategy_name]["tie"] += 1
                else:
                    results[strategy_name]["lose"] += 1

        # 결과 출력
        print(f"\n  {'전략':<20} {'낙찰':>8} {'동가':>8} {'탈락':>8} {'실격':>8} {'낙찰률':>10}")
        print("  " + "-" * 66)

        for name in STRATEGIES:
            r = results[name]
            valid = r["win"] + r["tie"] + r["lose"]
            win_rate = r["win"] / valid * 100 if valid > 0 else 0
            tie_rate = r["tie"] / valid * 100 if valid > 0 else 0
            print(f"  {name:<20} {r['win']:>8,} {r['tie']:>8,} {r['lose']:>8,} {r['disqualified']:>8,} {win_rate:>9.1f}%")

        # 베스트 전략의 연도별 낙찰률
        best_strategy = "하한율 +0.01%"
        print(f"\n  [{best_strategy}] 연도별 낙찰률:")
        for year in sorted(yearly_total.keys()):
            if yearly_total[year] > 0:
                yr_wins = yearly_wins[best_strategy][year]
                yr_rate = yr_wins / yearly_total[year] * 100
                print(f"    {year}: {yr_wins:>6,} / {yearly_total[year]:>6,} = {yr_rate:.1f}%")

        # 참여업체수별 낙찰률
        print(f"\n  [{best_strategy}] 참여업체수별 낙찰률:")
        for bucket in ["1-5", "6-10", "11-20", "21-50", "51+"]:
            if participant_total[bucket] > 0:
                bk_wins = participant_wins[best_strategy][bucket]
                bk_rate = bk_wins / participant_total[bucket] * 100
                print(f"    {bucket:>5}명: {bk_wins:>6,} / {participant_total[bucket]:>6,} = {bk_rate:.1f}%")

    conn.close()

    print(f"\n{'=' * 70}")
    print("백테스트 완료!")
    print("=" * 70)
    print("""
[해석 가이드]
- '낙찰': 우리 투찰률이 실제 낙찰자보다 하한율에 더 가까움 → 우리가 이김
- '동가': 실제 낙찰자와 동일한 투찰률 → 추첨 (50:50)
- '탈락': 실제 낙찰자가 더 하한율에 가까움 → 우리가 짐
- '실격': 하한율 미만 투찰 (무효)

※ 이 백테스트는 '1:1 대결'(우리 vs 실제 낙찰자) 기준입니다.
   실제로는 다수 참여자가 있으므로, 낙찰률이 이보다 낮을 수 있습니다.
""")


if __name__ == "__main__":
    run_backtest()
