"""
끝자리 패턴 분석
- 낙찰가의 끝자리(10원, 100원, 1000원 단위) 분포
- 하한선 대비 여유분의 미세 패턴
- 투찰가 끝자리 조정으로 낙찰률 개선 가능성
"""

import json
import math
from pathlib import Path
from collections import Counter, defaultdict

DATA_DIR = Path(__file__).parent.parent / "data"
LOWER_LIMIT_RATE = 87.745


def load_all():
    all_data = []
    for year in range(2021, 2026):
        f = DATA_DIR / f"opening_results_{year}.json"
        if f.exists():
            items = json.load(open(f))
            for item in items:
                if item.get("basic_price", 0) > 0 and item.get("reserved_price", 0) > 0 and item.get("winner_price", 0) > 0:
                    all_data.append(item)
    return all_data


def main():
    data = load_all()
    print(f"분석 대상: {len(data)}건\n")

    # ===== 1. 낙찰가 끝자리 패턴 =====
    print("=" * 60)
    print("  [1] 낙찰가 끝자리 분포")
    print("=" * 60)

    # 10원 단위 끝자리 (0~90)
    last_10 = Counter()
    # 100원 단위 끝자리 (0~900)
    last_100 = Counter()
    # 1000원 단위 끝자리 (0~9000)
    last_1000 = Counter()

    for item in data:
        wp = int(item["winner_price"])
        last_10[wp % 100] += 1      # 10원 단위 (0, 10, 20, ..., 90)
        last_100[wp % 1000] += 1    # 100원 단위
        last_1000[wp % 10000] += 1  # 1000원 단위

    print("\n  10원 단위 끝자리 (0~90):")
    total = sum(last_10.values())
    expected = total / 10  # 균등분포 기대치
    for digit in range(0, 100, 10):
        cnt = last_10[digit]
        pct = cnt / total * 100
        bar = "█" * int(pct * 3)
        deviation = (cnt - expected) / expected * 100
        print(f"    {digit:>3}원: {cnt:>5}건 ({pct:>5.1f}%) {bar} [{deviation:+.1f}%]")

    print(f"\n  100원 단위 끝자리 (상위 10개):")
    for digit, cnt in last_100.most_common(10):
        pct = cnt / total * 100
        print(f"    {digit:>4}원: {cnt:>4}건 ({pct:>5.1f}%)")

    # ===== 2. 하한선 바로 위 구간 분석 =====
    print(f"\n{'='*60}")
    print("  [2] 하한선 대비 낙찰가 미세 여유분 분포")
    print("=" * 60)

    # 낙찰가 - 하한선 (원 단위)
    margins_won = []
    margins_pct = []

    for item in data:
        rp = item["reserved_price"]
        wp = item["winner_price"]
        lower_limit = rp * LOWER_LIMIT_RATE / 100
        margin = wp - lower_limit
        margin_pct = margin / lower_limit * 100 if lower_limit > 0 else 0
        margins_won.append(margin)
        margins_pct.append(margin_pct)

    # 구간별 분포
    pct_brackets = [
        (0, 0.01), (0.01, 0.02), (0.02, 0.05), (0.05, 0.1),
        (0.1, 0.2), (0.2, 0.5), (0.5, 1.0), (1.0, 2.0), (2.0, 100)
    ]

    print(f"\n  낙찰가의 하한선 대비 여유분 분포:")
    cumulative = 0
    for lo, hi in pct_brackets:
        cnt = sum(1 for m in margins_pct if lo <= m < hi)
        pct = cnt / len(margins_pct) * 100
        cumulative += pct
        bar = "█" * int(pct * 2)
        print(f"    {lo:>5.2f}% ~ {hi:>5.2f}%: {cnt:>5}건 ({pct:>5.1f}%) 누적{cumulative:>5.1f}% {bar}")

    # ===== 3. "아깝게 진" 건들의 패턴 =====
    print(f"\n{'='*60}")
    print("  [3] 아깝게 진 건들의 패턴 분석")
    print("=" * 60)

    # 현재 알고리즘으로 투찰했을 때 아깝게 진 건들
    close_losses = []  # (차이(원), 차이(%), 기초금액, 입찰방법)

    for item in data:
        bp = item["basic_price"]
        rp = item["reserved_price"]
        wp = item["winner_price"]
        method = item.get("bid_method", "기타")

        lower_limit = rp * LOWER_LIMIT_RATE / 100

        # 현재 알고리즘 투찰가 계산 (간략화)
        bracket = "small" if bp < 1e8 else "medium" if bp < 5e8 else "large" if bp < 1e9 else "xlarge" if bp < 5e9 else "xxlarge"

        strategies = {
            "적격심사제": {"small": (-1.0, 1.4), "medium": (0.7, 0.2), "large": (-0.9, 1.5), "xlarge": (-0.2, 0.9), "xxlarge": (-0.7, 1.5)},
            "소액수의견적": {"small": (-0.2, 0.9), "medium": (0.6, 0.3), "large": (0.6, 0.3), "xlarge": (0.6, 0.3), "xxlarge": (0.6, 0.3)},
        }
        strat = strategies.get(method, strategies["소액수의견적"])
        adj, margin = strat.get(bracket, (-0.3, 1.0))

        predicted = bp * (1 + adj / 100)
        target_rate = LOWER_LIMIT_RATE + margin
        our_price = math.floor(predicted * target_rate / 100 / 10) * 10

        # 하한선 통과 + 낙찰 실패 (우리 가격 > 낙찰가)
        if our_price >= lower_limit and our_price > wp:
            diff = our_price - wp
            diff_pct = diff / wp * 100 if wp > 0 else 0
            close_losses.append({
                "diff": diff,
                "diff_pct": diff_pct,
                "our_price": our_price,
                "win_price": wp,
                "basic_price": bp,
                "method": method,
                "bracket": bracket,
            })

    close_losses.sort(key=lambda x: x["diff"])

    print(f"\n  하한선 통과했지만 낙찰 실패: {len(close_losses)}건")

    # 차이 분포
    diff_brackets = [
        (0, 100), (100, 1000), (1000, 5000), (5000, 10000),
        (10000, 50000), (50000, 100000), (100000, float("inf"))
    ]
    print(f"\n  낙찰가 대비 초과 금액 분포:")
    for lo, hi in diff_brackets:
        cnt = sum(1 for cl in close_losses if lo <= cl["diff"] < hi)
        pct = cnt / len(close_losses) * 100 if close_losses else 0
        hi_str = f"{hi:,.0f}" if hi != float("inf") else "∞"
        print(f"    {lo:>8,} ~ {hi_str:>10}원: {cnt:>4}건 ({pct:>5.1f}%)")

    # 10원~1000원 차이 건들 상세
    very_close = [cl for cl in close_losses if cl["diff"] < 1000]
    print(f"\n  1,000원 미만 차이 (= 10원 조정으로 뒤집을 수 있는 건): {len(very_close)}건")
    for cl in very_close[:20]:
        print(f"    차이 {cl['diff']:>6,}원 | 우리 {cl['our_price']:>14,} vs 낙찰 {cl['win_price']:>14,.0f}")

    # ===== 4. 10원 단위 미세 조정 시뮬레이션 =====
    print(f"\n{'='*60}")
    print("  [4] 10원 단위 미세 조정 시뮬레이션")
    print("=" * 60)

    # 현재: floor(가격 / 10) * 10 (내림)
    # 대안들:
    # - floor 그대로 (현재)
    # - floor 후 -10원 (더 공격적)
    # - floor 후 -20원
    # - floor 후 -30원
    # - round (반올림)

    adjustments = [0, -10, -20, -30, -50, -100, -200, -500, -1000]

    print(f"\n  투찰가 미세 조정 (기존 계산가에서 N원 감산):")
    print(f"  {'조정':>8} {'낙찰':>6} {'낙찰률':>8} {'하한통과':>8} {'통과율':>8} {'변화':>8}")
    print(f"  {'-'*55}")

    base_wins = 0  # 조정 0일 때 기준

    for adj_won in adjustments:
        wins = 0
        passes = 0
        total = 0

        for item in data:
            bp = item["basic_price"]
            rp = item["reserved_price"]
            wp = item["winner_price"]
            method = item.get("bid_method", "기타")

            lower_limit = rp * LOWER_LIMIT_RATE / 100
            bracket = "small" if bp < 1e8 else "medium" if bp < 5e8 else "large" if bp < 1e9 else "xlarge" if bp < 5e9 else "xxlarge"

            strategies = {
                "적격심사제": {"small": (-1.0, 1.4), "medium": (0.7, 0.2), "large": (-0.9, 1.5), "xlarge": (-0.2, 0.9), "xxlarge": (-0.7, 1.5)},
                "소액수의견적": {"small": (-0.2, 0.9), "medium": (0.6, 0.3), "large": (0.6, 0.3), "xlarge": (0.6, 0.3), "xxlarge": (0.6, 0.3)},
            }
            strat = strategies.get(method, strategies["소액수의견적"])
            a, m = strat.get(bracket, (-0.3, 1.0))

            predicted = bp * (1 + a / 100)
            target_rate = LOWER_LIMIT_RATE + m
            our_price = math.floor(predicted * target_rate / 100 / 10) * 10 + adj_won

            total += 1
            if our_price >= lower_limit:
                passes += 1
                if our_price <= wp:
                    wins += 1

        if adj_won == 0:
            base_wins = wins

        wr = wins / total * 100
        pr = passes / total * 100
        diff = wins - base_wins
        print(f"  {adj_won:>+7}원 {wins:>5}건 {wr:>7.1f}% {passes:>7}건 {pr:>7.1f}% {diff:>+7}건")

    # ===== 5. 입찰방법별 미세 조정 =====
    print(f"\n{'='*60}")
    print("  [5] 입찰방법별 최적 미세 조정")
    print("=" * 60)

    for method in ["소액수의견적", "적격심사제"]:
        method_data = [d for d in data if d.get("bid_method") == method]
        if not method_data:
            continue

        print(f"\n  {method} ({len(method_data)}건):")
        print(f"  {'조정':>8} {'낙찰':>6} {'낙찰률':>8} {'하한통과율':>8}")
        print(f"  {'-'*40}")

        for adj_won in [0, -10, -20, -50, -100, -200, -500]:
            wins = 0
            passes = 0

            for item in method_data:
                bp = item["basic_price"]
                rp = item["reserved_price"]
                wp = item["winner_price"]

                lower_limit = rp * LOWER_LIMIT_RATE / 100
                bracket = "small" if bp < 1e8 else "medium" if bp < 5e8 else "large" if bp < 1e9 else "xlarge" if bp < 5e9 else "xxlarge"

                strategies = {
                    "적격심사제": {"small": (-1.0, 1.4), "medium": (0.7, 0.2), "large": (-0.9, 1.5), "xlarge": (-0.2, 0.9), "xxlarge": (-0.7, 1.5)},
                    "소액수의견적": {"small": (-0.2, 0.9), "medium": (0.6, 0.3), "large": (0.6, 0.3), "xlarge": (0.6, 0.3), "xxlarge": (0.6, 0.3)},
                }
                strat = strategies.get(method, strategies["소액수의견적"])
                a, m = strat.get(bracket, (-0.3, 1.0))

                predicted = bp * (1 + a / 100)
                target_rate = LOWER_LIMIT_RATE + m
                our_price = math.floor(predicted * target_rate / 100 / 10) * 10 + adj_won

                if our_price >= lower_limit:
                    passes += 1
                    if our_price <= wp:
                        wins += 1

            wr = wins / len(method_data) * 100
            pr = passes / len(method_data) * 100
            print(f"  {adj_won:>+7}원 {wins:>5}건 {wr:>7.1f}% {pr:>7.1f}%")


if __name__ == "__main__":
    main()
