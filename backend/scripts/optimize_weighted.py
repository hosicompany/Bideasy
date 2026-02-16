"""
연도별 가중치 적용 최적 파라미터 탐색
최근 연도에 가중치를 높여 시장 트렌드 반영

가중치: 2021=1x, 2022=1x, 2023=1.5x, 2024=2x, 2025=3x
"""

import json
import math
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"
LOWER_LIMIT_RATE = 87.745

# 연도별 가중치 (최근에 높은 가중치)
YEAR_WEIGHTS = {
    2021: 1.0,
    2022: 1.0,
    2023: 1.5,
    2024: 2.0,
    2025: 3.0,
}


def load_all():
    all_data = []
    for year in range(2021, 2026):
        f = DATA_DIR / f"opening_results_{year}.json"
        if not f.exists():
            continue
        with open(f) as fh:
            items = json.load(fh)
        for item in items:
            if item.get("basic_price", 0) > 0 and item.get("reserved_price", 0) > 0 and item.get("winner_price", 0) > 0:
                # 연도 추출
                od = item.get("open_date", "")
                y = int(od[:4]) if od and len(od) >= 4 else year
                item["_year"] = y
                item["_weight"] = YEAR_WEIGHTS.get(y, 1.0)
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


def weighted_grid_search(items, pass_threshold=90.0):
    """가중치 적용 그리드 서치"""
    best = None
    best_score = 0
    total_weight = sum(i["_weight"] for i in items)

    for adj_x10 in range(-10, 16):
        adj = adj_x10 / 10
        for margin_x10 in range(0, 16):
            margin = margin_x10 / 10

            win_weight = 0
            pass_weight = 0

            for item in items:
                bp = item["basic_price"]
                rp = item["reserved_price"]
                wp = item["winner_price"]
                w = item["_weight"]

                predicted = bp * (1 + adj / 100)
                target_rate = LOWER_LIMIT_RATE + margin
                target_price = math.floor(predicted * target_rate / 100 / 10) * 10
                lower_limit = rp * LOWER_LIMIT_RATE / 100

                if target_price >= lower_limit:
                    pass_weight += w
                    if target_price <= wp:
                        win_weight += w

            pass_rate = pass_weight / total_weight * 100
            win_rate = win_weight / total_weight * 100

            if pass_rate >= pass_threshold and win_rate > best_score:
                best_score = win_rate
                best = {
                    "adjustment": adj,
                    "margin": margin,
                    "win_rate": round(win_rate, 2),
                    "pass_rate": round(pass_rate, 2),
                }

    return best


def main():
    data = load_all()
    print(f"유효 데이터: {len(data)}건")
    print(f"가중치: {YEAR_WEIGHTS}\n")

    # 입찰방법별 분류
    by_method = {}
    for item in data:
        method = item.get("bid_method", "기타")
        if method not in by_method:
            by_method[method] = []
        by_method[method].append(item)

    for method in ["소액수의견적", "적격심사제"]:
        items = by_method.get(method, [])
        if not items:
            continue

        print(f"{'='*60}")
        print(f"  {method} ({len(items)}건)")
        print(f"{'='*60}")

        # 전체 최적
        result = weighted_grid_search(items)
        if result:
            print(f"  [전체] 보정 {result['adjustment']:+.1f}%, 여유분 {result['margin']:.1f}%p")
            print(f"         낙찰 {result['win_rate']}%, 통과 {result['pass_rate']}%")

        # 금액대별
        by_bracket = {}
        for item in items:
            b = get_bracket(item["basic_price"])
            if b not in by_bracket:
                by_bracket[b] = []
            by_bracket[b].append(item)

        for bracket in ["small", "medium", "large", "xlarge", "xxlarge"]:
            bracket_items = by_bracket.get(bracket, [])
            if len(bracket_items) < 5:
                print(f"  [{bracket}] {len(bracket_items)}건 - 표본 부족")
                continue

            result = weighted_grid_search(bracket_items)
            if result:
                print(f"  [{bracket}] {len(bracket_items)}건 → "
                      f"보정 {result['adjustment']:+.1f}%, 여유분 {result['margin']:.1f}%p, "
                      f"낙찰 {result['win_rate']}%, 통과 {result['pass_rate']}%")
            else:
                print(f"  [{bracket}] {len(bracket_items)}건 - 90% 통과 가능 조합 없음")

    # 비교: 가중치 없는 결과 vs 가중치 있는 결과
    print(f"\n{'='*60}")
    print("  비교: 균등 가중치 vs 최신 가중치")
    print(f"{'='*60}")

    for method in ["소액수의견적", "적격심사제"]:
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

            # 균등
            for item in bracket_items:
                item["_weight"] = 1.0
            r1 = weighted_grid_search(bracket_items)

            # 최신 가중치 복원
            for item in bracket_items:
                item["_weight"] = YEAR_WEIGHTS.get(item["_year"], 1.0)
            r2 = weighted_grid_search(bracket_items)

            if r1 and r2:
                diff = "변화" if r1["adjustment"] != r2["adjustment"] or r1["margin"] != r2["margin"] else "동일"
                print(f"    [{bracket}] 균등({r1['adjustment']:+.1f},{r1['margin']:.1f}) "
                      f"vs 가중({r2['adjustment']:+.1f},{r2['margin']:.1f}) [{diff}]")


if __name__ == "__main__":
    main()
