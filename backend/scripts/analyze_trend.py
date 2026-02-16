"""
연도별 트렌드 분석
- 연도별 기초금액 대비 예정가격 오차 평균
- 연도별 낙찰률 패턴 변화
- 연도별 최적 파라미터 변화
"""

import json
import math
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"
LOWER_LIMIT_RATE = 87.745


def load_year(year):
    f = DATA_DIR / f"opening_results_{year}.json"
    if not f.exists():
        return []
    with open(f) as fh:
        items = json.load(fh)
    return [i for i in items if i.get("basic_price", 0) > 0 and i.get("reserved_price", 0) > 0 and i.get("winner_price", 0) > 0]


def analyze_year(items, year):
    """연도별 기초 통계"""
    if not items:
        return None

    deviations = []  # 기초금액 대비 예정가격 오차
    win_rates = []   # 낙찰률 (실제)

    for item in items:
        bp = item["basic_price"]
        rp = item["reserved_price"]
        dev = (rp - bp) / bp * 100
        deviations.append(dev)
        win_rates.append(item.get("winner_rate", 0) or item.get("bid_rate", 0))

    avg_dev = sum(deviations) / len(deviations)
    median_dev = sorted(deviations)[len(deviations) // 2]

    # 오차 분포
    within_1 = sum(1 for d in deviations if abs(d) <= 1.0) / len(deviations) * 100
    positive = sum(1 for d in deviations if d > 0) / len(deviations) * 100

    avg_wr = sum(win_rates) / len(win_rates) if win_rates else 0

    return {
        "year": year,
        "count": len(items),
        "avg_deviation": round(avg_dev, 3),
        "median_deviation": round(median_dev, 3),
        "within_1pct": round(within_1, 1),
        "positive_pct": round(positive, 1),
        "avg_winner_rate": round(avg_wr, 3),
    }


def grid_search_year(items):
    """연도별 최적 파라미터"""
    best = None
    best_wr = 0

    for adj_x10 in range(-10, 16):
        adj = adj_x10 / 10
        for margin_x10 in range(0, 16):
            margin = margin_x10 / 10
            wins = 0
            passes = 0
            total = len(items)

            for item in items:
                bp = item["basic_price"]
                rp = item["reserved_price"]
                wp = item["winner_price"]

                predicted = bp * (1 + adj / 100)
                target_rate = LOWER_LIMIT_RATE + margin
                target_price = math.floor(predicted * target_rate / 100 / 10) * 10
                lower_limit = rp * LOWER_LIMIT_RATE / 100

                if target_price >= lower_limit:
                    passes += 1
                    if target_price <= wp:
                        wins += 1

            pr = passes / total * 100 if total > 0 else 0
            wr = wins / total * 100 if total > 0 else 0

            if pr >= 90.0 and wr > best_wr:
                best_wr = wr
                best = (adj, margin, wr, pr)

    return best


def main():
    print("=" * 60)
    print("  연도별 트렌드 분석")
    print("=" * 60)

    print("\n[ 연도별 기초 통계 ]")
    print(f"{'연도':>6} {'건수':>6} {'예정가오차평균':>12} {'중앙값':>8} {'±1%이내':>8} {'양수비율':>8} {'평균낙찰률':>10}")
    print("-" * 70)

    all_items_by_year = {}
    for year in range(2021, 2026):
        items = load_year(year)
        all_items_by_year[year] = items
        stats = analyze_year(items, year)
        if stats:
            print(f"{stats['year']:>6} {stats['count']:>6} {stats['avg_deviation']:>+10.3f}% "
                  f"{stats['median_deviation']:>+7.3f}% {stats['within_1pct']:>7.1f}% "
                  f"{stats['positive_pct']:>7.1f}% {stats['avg_winner_rate']:>9.3f}%")

    print("\n[ 연도별 최적 파라미터 ]")
    print(f"{'연도':>6} {'건수':>6} {'보정':>8} {'여유분':>8} {'낙찰률':>8} {'통과율':>8}")
    print("-" * 52)

    for year in range(2021, 2026):
        items = all_items_by_year[year]
        if not items:
            continue
        result = grid_search_year(items)
        if result:
            adj, margin, wr, pr = result
            print(f"{year:>6} {len(items):>6} {adj:>+7.1f}% {margin:>7.1f}%p {wr:>7.1f}% {pr:>7.1f}%")

    # 입찰방법별 연도 트렌드
    for method in ["소액수의견적", "적격심사제"]:
        print(f"\n[ {method} — 연도별 최적 파라미터 ]")
        print(f"{'연도':>6} {'건수':>6} {'보정':>8} {'여유분':>8} {'낙찰률':>8} {'통과율':>8}")
        print("-" * 52)

        for year in range(2021, 2026):
            items = [i for i in all_items_by_year[year] if i.get("bid_method") == method]
            if len(items) < 10:
                print(f"{year:>6} {len(items):>6} 표본 부족")
                continue
            result = grid_search_year(items)
            if result:
                adj, margin, wr, pr = result
                print(f"{year:>6} {len(items):>6} {adj:>+7.1f}% {margin:>7.1f}%p {wr:>7.1f}% {pr:>7.1f}%")


if __name__ == "__main__":
    main()
