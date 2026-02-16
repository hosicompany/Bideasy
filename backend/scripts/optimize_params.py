"""
입찰방법 + 금액대별 최적 파라미터 탐색
그리드 서치: adjustment (-1.0 ~ +1.5), margin (0.0 ~ 1.5)
목표: 하한통과 90%+ 조건에서 최고 낙찰률
"""

import json
import math
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"

LOWER_LIMIT_RATE = 87.745  # 공사


def load_data():
    all_data = []
    for year in range(2021, 2027):
        f = DATA_DIR / f"opening_results_{year}.json"
        if f.exists():
            with open(f) as fh:
                items = json.load(fh)
            for item in items:
                bp = item.get("basic_price", 0)
                rp = item.get("reserved_price", 0)
                wp = item.get("winner_price", 0)
                if bp > 0 and rp > 0 and wp > 0:
                    all_data.append(item)
    return all_data


def get_bracket(basic_price):
    if basic_price < 1e8:
        return "small"
    elif basic_price < 5e8:
        return "medium"
    elif basic_price < 1e9:
        return "large"
    elif basic_price < 5e9:
        return "xlarge"
    else:
        return "xxlarge"


def simulate(items, adjustment, margin):
    """주어진 파라미터로 낙찰 시뮬레이션"""
    wins = 0
    passes = 0
    total = len(items)
    if total == 0:
        return 0, 0, 0

    for item in items:
        bp = item["basic_price"]
        rp = item["reserved_price"]
        wp = item["winner_price"]

        # 예정가격 예측: 기초금액 + 보정
        predicted = bp * (1 + adjustment / 100)
        # 투찰률 = 하한율 + 여유분
        target_rate = LOWER_LIMIT_RATE + margin
        target_price = math.floor(predicted * target_rate / 100 / 10) * 10

        # 하한선: 예정가격 * 하한율
        lower_limit = rp * LOWER_LIMIT_RATE / 100

        if target_price >= lower_limit:
            passes += 1
            # 낙찰 조건: 하한선 이상이면서 실제 낙찰가 이하
            if target_price <= wp:
                wins += 1

    return wins, passes, total


def grid_search(items, label=""):
    """그리드 서치로 최적 파라미터 탐색"""
    best = None
    best_win_rate = 0

    # adjustment: -1.0 ~ +1.5 (0.1 간격)
    # margin: 0.0 ~ 1.5 (0.1 간격)
    for adj_x10 in range(-10, 16):
        adj = adj_x10 / 10
        for margin_x10 in range(0, 16):
            margin = margin_x10 / 10
            wins, passes, total = simulate(items, adj, margin)

            pass_rate = passes / total * 100 if total > 0 else 0
            win_rate = wins / total * 100 if total > 0 else 0

            # 하한통과 90% 이상 조건
            if pass_rate >= 90.0:
                if win_rate > best_win_rate:
                    best_win_rate = win_rate
                    best = {
                        "adjustment": adj,
                        "margin": margin,
                        "win_rate": round(win_rate, 2),
                        "pass_rate": round(pass_rate, 2),
                        "wins": wins,
                        "passes": passes,
                        "total": total,
                    }

    return best


def main():
    data = load_data()
    print(f"유효 데이터: {len(data)}건\n")

    # 입찰방법별 분류
    by_method = {}
    for item in data:
        method = item.get("bid_method", "기타")
        if method not in by_method:
            by_method[method] = []
        by_method[method].append(item)

    # 주요 입찰방법만
    target_methods = ["소액수의견적", "적격심사제"]

    for method in target_methods:
        items = by_method.get(method, [])
        if not items:
            continue

        print(f"{'='*60}")
        print(f"  {method} ({len(items)}건)")
        print(f"{'='*60}")

        # 금액대별 분류
        by_bracket = {}
        for item in items:
            b = get_bracket(item["basic_price"])
            if b not in by_bracket:
                by_bracket[b] = []
            by_bracket[b].append(item)

        for bracket in ["small", "medium", "large", "xlarge", "xxlarge"]:
            bracket_items = by_bracket.get(bracket, [])
            if len(bracket_items) < 5:
                print(f"  [{bracket}] {len(bracket_items)}건 - 표본 부족, 스킵")
                continue

            result = grid_search(bracket_items, f"{method}-{bracket}")
            if result:
                print(f"  [{bracket}] {result['total']}건")
                print(f"    최적: 보정 {result['adjustment']:+.1f}%, 여유분 {result['margin']:.1f}%p")
                print(f"    낙찰 {result['win_rate']}% ({result['wins']}건), 통과 {result['pass_rate']}%")
            else:
                print(f"  [{bracket}] {len(bracket_items)}건 - 90% 통과 가능한 조합 없음")
            print()

    # 하한 통과율 85%로 완화한 탐색도 별도
    print(f"\n{'='*60}")
    print(f"  === 하한통과 85% 완화 기준 ===")
    print(f"{'='*60}")

    for method in target_methods:
        items = by_method.get(method, [])
        if not items:
            continue

        print(f"\n  {method}")
        by_bracket = {}
        for item in items:
            b = get_bracket(item["basic_price"])
            if b not in by_bracket:
                by_bracket[b] = []
            by_bracket[b].append(item)

        for bracket in ["small", "medium", "large", "xlarge", "xxlarge"]:
            bracket_items = by_bracket.get(bracket, [])
            if len(bracket_items) < 5:
                continue

            best = None
            best_wr = 0
            for adj_x10 in range(-10, 16):
                adj = adj_x10 / 10
                for margin_x10 in range(0, 16):
                    margin = margin_x10 / 10
                    wins, passes, total = simulate(bracket_items, adj, margin)
                    pr = passes / total * 100
                    wr = wins / total * 100
                    if pr >= 85.0 and wr > best_wr:
                        best_wr = wr
                        best = (adj, margin, wr, pr, wins, total)

            if best:
                adj, margin, wr, pr, wins, total = best
                print(f"    [{bracket}] 보정{adj:+.1f}%, 여유{margin:.1f}%p → 낙찰{wr:.1f}% 통과{pr:.1f}%")


if __name__ == "__main__":
    main()
