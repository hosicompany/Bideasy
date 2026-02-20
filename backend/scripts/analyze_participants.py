"""
참가업체수 기반 경쟁 강도 분석
- 참가업체수 분포
- 참가업체수별 낙찰 패턴
- 경쟁 강도 기반 전략 분화 시뮬레이션
"""

import json
import math
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"
LOWER_LIMIT_RATE = 87.745


def load_data():
    # 참가업체수
    pc_file = DATA_DIR / "participant_counts.json"
    pc_data = json.load(open(pc_file))
    pc_map = {item["bid_no"]: item["participant_count"] for item in pc_data}

    # 개찰 결과
    all_data = []
    for year in range(2021, 2026):
        f = DATA_DIR / f"opening_results_{year}.json"
        if f.exists():
            items = json.load(open(f))
            for item in items:
                bid_no = item.get("bid_no", "")
                if bid_no in pc_map and item.get("basic_price", 0) > 0 and item.get("reserved_price", 0) > 0 and item.get("winner_price", 0) > 0:
                    item["participant_count"] = pc_map[bid_no]
                    all_data.append(item)
    return all_data


def get_bracket(bp):
    if bp < 1e8: return "small"
    elif bp < 5e8: return "medium"
    elif bp < 1e9: return "large"
    elif bp < 5e9: return "xlarge"
    else: return "xxlarge"


def simulate(items, adj, margin):
    wins = 0
    passes = 0
    for item in items:
        bp = item["basic_price"]
        rp = item["reserved_price"]
        wp = item["winner_price"]
        predicted = bp * (1 + adj / 100)
        target_rate = LOWER_LIMIT_RATE + margin
        price = math.floor(predicted * target_rate / 100 / 10) * 10
        lower_limit = rp * LOWER_LIMIT_RATE / 100
        if price >= lower_limit:
            passes += 1
            if price <= wp:
                wins += 1
    return wins, passes, len(items)


def grid_search(items, pass_threshold=90.0):
    best = None
    best_wr = 0
    total = len(items)
    if total < 5:
        return None

    for adj_x10 in range(-10, 16):
        adj = adj_x10 / 10
        for margin_x10 in range(0, 16):
            margin = margin_x10 / 10
            wins, passes, _ = simulate(items, adj, margin)
            pr = passes / total * 100
            wr = wins / total * 100
            if pr >= pass_threshold and wr > best_wr:
                best_wr = wr
                best = {"adj": adj, "margin": margin, "wr": round(wr, 1), "pr": round(pr, 1), "wins": wins}
    return best


def main():
    data = load_data()
    print(f"분석 대상: {len(data)}건 (참가업체수 매칭)\n")

    # ===== 1. 참가업체수 분포 =====
    print("=" * 60)
    print("  [1] 참가업체수 분포")
    print("=" * 60)

    counts = [item["participant_count"] for item in data]
    counts_nz = [c for c in counts if c > 0]

    avg = sum(counts_nz) / len(counts_nz) if counts_nz else 0
    sorted_c = sorted(counts_nz)
    med = sorted_c[len(sorted_c) // 2] if sorted_c else 0

    print(f"  전체: {len(data)}건")
    print(f"  참가 0 제외: {len(counts_nz)}건")
    print(f"  평균: {avg:.0f}개, 중앙값: {med}개")
    print(f"  최소~최대: {min(counts_nz) if counts_nz else 0} ~ {max(counts_nz) if counts_nz else 0}개")

    brackets = [(1, 10), (11, 30), (31, 50), (51, 100), (101, 200), (201, 500), (501, 1000), (1001, 99999)]
    print("\n  참가업체수 구간별:")
    for lo, hi in brackets:
        cnt = sum(1 for c in counts_nz if lo <= c <= hi)
        pct = cnt / len(counts_nz) * 100 if counts_nz else 0
        hi_str = f"{hi}" if hi < 99999 else "∞"
        bar = "█" * int(pct / 2)
        print(f"    {lo:>5} ~ {hi_str:>5}: {cnt:>4}건 ({pct:>5.1f}%) {bar}")

    # ===== 2. 참가업체수별 낙찰 패턴 =====
    print(f"\n{'='*60}")
    print("  [2] 참가업체수별 낙찰가-하한선 간격")
    print("=" * 60)

    comp_brackets = [(1, 10, "극소"), (11, 30, "소"), (31, 100, "중"), (101, 300, "대"), (301, 99999, "극대")]

    for lo, hi, label in comp_brackets:
        bracket_items = [d for d in data if lo <= d["participant_count"] <= hi]
        if not bracket_items:
            continue

        margins = []
        for item in bracket_items:
            rp = item["reserved_price"]
            wp = item["winner_price"]
            ll = rp * LOWER_LIMIT_RATE / 100
            if ll > 0:
                margins.append((wp - ll) / ll * 100)

        avg_m = sum(margins) / len(margins) if margins else 0
        sorted_m = sorted(margins)
        med_m = sorted_m[len(sorted_m) // 2] if sorted_m else 0

        hi_str = f"{hi}" if hi < 99999 else "∞"
        print(f"  [{label}] {lo}~{hi_str}개 업체 ({len(bracket_items)}건)")
        print(f"    낙찰가 여유분: 평균 +{avg_m:.3f}%, 중앙값 +{med_m:.3f}%")
        rand_rate = 1 / ((lo + min(hi, 300)) / 2) * 100
        print(f"    이론 랜덤 낙찰률: {rand_rate:.1f}%")
        print()

    # ===== 3. 참가업체수별 현재 알고리즘 성적 =====
    print(f"{'='*60}")
    print("  [3] 참가업체수별 현재 알고리즘 성적")
    print("=" * 60)

    strategies = {
        "적격심사제": {"small": (-1.0, 1.4), "medium": (0.7, 0.2), "large": (-0.9, 1.5), "xlarge": (-0.2, 0.9), "xxlarge": (-0.7, 1.5)},
        "소액수의견적": {"small": (-0.2, 0.9), "medium": (0.6, 0.3), "large": (0.6, 0.3), "xlarge": (0.6, 0.3), "xxlarge": (0.6, 0.3)},
    }

    print(f"\n  {'경쟁강도':<10} {'건수':>6} {'낙찰':>6} {'낙찰률':>8} {'통과율':>8} {'랜덤':>8} {'vs랜덤':>8}")
    print(f"  {'-'*58}")

    for lo, hi, label in comp_brackets:
        bracket_items = [d for d in data if lo <= d["participant_count"] <= hi]
        if not bracket_items:
            continue

        wins = 0
        passes = 0
        for item in bracket_items:
            bp = item["basic_price"]
            rp = item["reserved_price"]
            wp = item["winner_price"]
            method = item.get("bid_method", "기타")
            bracket = get_bracket(bp)

            strat = strategies.get(method, strategies["소액수의견적"])
            adj, margin = strat.get(bracket, (-0.3, 1.0))

            predicted = bp * (1 + adj / 100)
            target_rate = LOWER_LIMIT_RATE + margin
            price = math.floor(predicted * target_rate / 100 / 10) * 10
            lower_limit = rp * LOWER_LIMIT_RATE / 100

            if price >= lower_limit:
                passes += 1
                if price <= wp:
                    wins += 1

        total = len(bracket_items)
        wr = wins / total * 100
        pr = passes / total * 100
        avg_cnt = sum(d["participant_count"] for d in bracket_items) / total
        rand = 1 / avg_cnt * 100 if avg_cnt > 0 else 0
        vs_rand = wr / rand if rand > 0 else 0

        hi_str = f"{hi}" if hi < 99999 else "∞"
        print(f"  {label}({lo}~{hi_str}){'':<3} {total:>5} {wins:>5} {wr:>7.1f}% {pr:>7.1f}% {rand:>7.1f}% {vs_rand:>7.1f}x")

    # ===== 4. 참가업체수별 최적 파라미터 =====
    print(f"\n{'='*60}")
    print("  [4] 참가업체수별 최적 파라미터 (그리드서치)")
    print("=" * 60)

    for lo, hi, label in comp_brackets:
        bracket_items = [d for d in data if lo <= d["participant_count"] <= hi]
        if len(bracket_items) < 10:
            continue

        result = grid_search(bracket_items)
        hi_str = f"{hi}" if hi < 99999 else "∞"
        if result:
            print(f"  [{label}] {lo}~{hi_str}개 ({len(bracket_items)}건)")
            print(f"    최적: 보정{result['adj']:+.1f}%, 여유{result['margin']:.1f}%p → 낙찰{result['wr']}% 통과{result['pr']}%")
        print()

    # ===== 5. 입찰방법 × 참가업체수 교차분석 =====
    print(f"{'='*60}")
    print("  [5] 입찰방법 × 참가업체수 교차분석")
    print("=" * 60)

    for method in ["소액수의견적", "적격심사제"]:
        method_items = [d for d in data if d.get("bid_method") == method]
        if not method_items:
            continue

        print(f"\n  {method} ({len(method_items)}건)")
        print(f"  {'경쟁강도':<10} {'건수':>6} {'현재낙찰률':>10} {'최적낙찰률':>10} {'최적파라미터':>20}")
        print(f"  {'-'*60}")

        for lo, hi, label in comp_brackets:
            items = [d for d in method_items if lo <= d["participant_count"] <= hi]
            if len(items) < 5:
                continue

            # 현재 전략
            strat = strategies.get(method, strategies["소액수의견적"])
            current_wins = 0
            for item in items:
                bp = item["basic_price"]
                rp = item["reserved_price"]
                wp = item["winner_price"]
                bracket = get_bracket(bp)
                adj, margin = strat.get(bracket, (-0.3, 1.0))
                predicted = bp * (1 + adj / 100)
                price = math.floor(predicted * (LOWER_LIMIT_RATE + margin) / 100 / 10) * 10
                ll = rp * LOWER_LIMIT_RATE / 100
                if price >= ll and price <= wp:
                    current_wins += 1

            current_wr = current_wins / len(items) * 100

            # 최적
            result = grid_search(items)
            hi_str = f"{hi}" if hi < 99999 else "∞"
            if result:
                print(f"  {label}({lo}~{hi_str}){'':<3} {len(items):>5} {current_wr:>9.1f}% {result['wr']:>9.1f}% "
                      f"  ({result['adj']:+.1f}%, {result['margin']:.1f}%p)")
            else:
                print(f"  {label}({lo}~{hi_str}){'':<3} {len(items):>5} {current_wr:>9.1f}% {'N/A':>9}")


if __name__ == "__main__":
    main()
