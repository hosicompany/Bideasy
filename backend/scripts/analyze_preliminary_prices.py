"""
복수예비가격 데이터 분석
1. 기본 통계: 15개 예비가격의 분포 특성
2. 예정가격 예측 정확도: 확률분포 vs 기초금액 단순예측
3. 시뮬레이션: 복수예비가격 기반 투찰 시 낙찰률 변화
4. 실전 활용 가능성 검토
"""

import json
import math
from itertools import combinations
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"
LOWER_LIMIT_RATE = 87.745


def load_preliminary():
    f = DATA_DIR / "preliminary_prices.json"
    with open(f) as fh:
        return json.load(fh)


def load_opening_results():
    """개찰 결과 데이터 (낙찰가 포함)"""
    by_bid_no = {}
    for year in range(2021, 2026):
        f = DATA_DIR / f"opening_results_{year}.json"
        if f.exists():
            items = json.load(open(f))
            for item in items:
                by_bid_no[item.get("bid_no", "")] = item
    return by_bid_no


def main():
    prelim_data = load_preliminary()
    opening_data = load_opening_results()

    print(f"복수예비가격 데이터: {len(prelim_data)}건")
    print()

    # ===== 1. 기본 통계 =====
    print("=" * 60)
    print("  [1] 복수예비가격 기본 통계")
    print("=" * 60)

    price_counts = []
    drawn_counts = []
    spreads = []  # 최대-최소 / 기초금액
    basic_vs_avg = []  # 기초금액 vs 15개 평균

    for item in prelim_data:
        prices = [p["price"] for p in item["preliminary_prices"] if p["price"] > 0]
        drawn = [p for p in item["preliminary_prices"] if p["drawn"] and p["price"] > 0]
        bp = item["basic_price"]

        price_counts.append(len(prices))
        drawn_counts.append(len(drawn))

        if prices and bp > 0:
            spread = (max(prices) - min(prices)) / bp * 100
            spreads.append(spread)
            avg_15 = sum(prices) / len(prices)
            basic_vs_avg.append((avg_15 - bp) / bp * 100)

    print(f"  예비가격 개수: 평균 {sum(price_counts)/len(price_counts):.1f}개")
    print(f"  추첨 개수: 평균 {sum(drawn_counts)/len(drawn_counts):.1f}개")
    print(f"  예비가격 범위(max-min): 평균 ±{sum(spreads)/len(spreads)/2:.2f}%")
    print(f"  기초금액 vs 15개 평균: {sum(basic_vs_avg)/len(basic_vs_avg):+.3f}%")

    # ===== 2. 확률분포 분석 =====
    print(f"\n{'='*60}")
    print("  [2] C(15,4) 확률분포 vs 실제 예정가격")
    print("=" * 60)

    prediction_errors_basic = []  # 기초금액 기반 오차
    prediction_errors_median = [] # 확률분포 중앙값 오차

    matched = 0
    for item in prelim_data:
        bid_no = item["bid_no"]
        opening = opening_data.get(bid_no)
        if not opening:
            continue

        rp = opening.get("reserved_price", 0)
        bp = opening.get("basic_price", 0)
        wp = opening.get("winner_price", 0)
        if rp <= 0 or bp <= 0 or wp <= 0:
            continue

        matched += 1

        prices = [p["price"] for p in item["preliminary_prices"] if p["price"] > 0]
        if len(prices) < 4:
            continue

        # C(n, 4) 조합의 평균 = 가능한 예정가격들
        len(prices)
        possible_rps = []
        for combo in combinations(prices, 4):
            possible_rps.append(sum(combo) / 4)

        # 확률분포 중앙값
        sorted_rps = sorted(possible_rps)
        median_rp = sorted_rps[len(sorted_rps) // 2]

        # 기초금액 기반 오차
        err_basic = (rp - bp) / bp * 100
        prediction_errors_basic.append(err_basic)

        # 확률분포 중앙값 기반 오차
        err_median = (rp - median_rp) / median_rp * 100
        prediction_errors_median.append(err_median)

    print(f"  매칭 건수: {matched}건")
    print()

    # 오차 비교
    abs_basic = [abs(e) for e in prediction_errors_basic]
    abs_median = [abs(e) for e in prediction_errors_median]

    avg_basic = sum(abs_basic) / len(abs_basic)
    avg_median = sum(abs_median) / len(abs_median)

    within_1_basic = sum(1 for e in abs_basic if e <= 1.0) / len(abs_basic) * 100
    within_05_basic = sum(1 for e in abs_basic if e <= 0.5) / len(abs_basic) * 100
    within_01_basic = sum(1 for e in abs_basic if e <= 0.1) / len(abs_basic) * 100

    within_1_median = sum(1 for e in abs_median if e <= 1.0) / len(abs_median) * 100
    within_05_median = sum(1 for e in abs_median if e <= 0.5) / len(abs_median) * 100
    within_01_median = sum(1 for e in abs_median if e <= 0.1) / len(abs_median) * 100

    print(f"  {'지표':<25} {'기초금액':>12} {'확률분포중앙값':>12} {'개선':>8}")
    print(f"  {'-'*60}")
    print(f"  {'평균 절대 오차':<25} {avg_basic:>11.3f}% {avg_median:>11.3f}% {(avg_basic-avg_median)/avg_basic*100:>+7.1f}%")
    print(f"  {'±0.1% 이내':<25} {within_01_basic:>11.1f}% {within_01_median:>11.1f}% {within_01_median-within_01_basic:>+7.1f}%p")
    print(f"  {'±0.5% 이내':<25} {within_05_basic:>11.1f}% {within_05_median:>11.1f}% {within_05_median-within_05_basic:>+7.1f}%p")
    print(f"  {'±1.0% 이내':<25} {within_1_basic:>11.1f}% {within_1_median:>11.1f}% {within_1_median-within_1_basic:>+7.1f}%p")

    # ===== 3. 낙찰 시뮬레이션 =====
    print(f"\n{'='*60}")
    print("  [3] 복수예비가격 기반 투찰 시뮬레이션")
    print("=" * 60)

    # 전략 A: 기존 (기초금액 기반)
    # 전략 B: 확률분포 중앙값 기반
    # 전략 C: 확률분포 최적 구간 (하한선 바로 위)

    wins_a = 0
    wins_b = 0
    wins_c = 0
    passes_a = 0
    passes_b = 0
    passes_c = 0
    total = 0

    for item in prelim_data:
        bid_no = item["bid_no"]
        opening = opening_data.get(bid_no)
        if not opening:
            continue

        rp = opening.get("reserved_price", 0)
        bp = opening.get("basic_price", 0)
        wp = opening.get("winner_price", 0)
        if rp <= 0 or bp <= 0 or wp <= 0:
            continue

        prices = [p["price"] for p in item["preliminary_prices"] if p["price"] > 0]
        if len(prices) < 4:
            continue

        total += 1
        lower_limit = rp * LOWER_LIMIT_RATE / 100

        # 전략 A: 기초금액 기반 (현재 알고리즘, 적격심사제 medium 파라미터)
        adj_a = 0.7  # 현재 적격심사제 medium
        margin_a = 0.2
        pred_a = bp * (1 + adj_a / 100)
        target_rate_a = LOWER_LIMIT_RATE + margin_a
        price_a = math.floor(pred_a * target_rate_a / 100 / 10) * 10

        if price_a >= lower_limit:
            passes_a += 1
            if price_a <= wp:
                wins_a += 1

        # 전략 B: 확률분포 중앙값 기반
        possible_rps = sorted([sum(c) / 4 for c in combinations(prices, 4)])
        median_rp = possible_rps[len(possible_rps) // 2]
        margin_b = 0.2
        target_rate_b = LOWER_LIMIT_RATE + margin_b
        price_b = math.floor(median_rp * target_rate_b / 100 / 10) * 10

        if price_b >= lower_limit:
            passes_b += 1
            if price_b <= wp:
                wins_b += 1

        # 전략 C: 확률분포 활용 최적 (각 가능한 예정가격의 하한선 분포)
        # 가능한 하한선들 중 상위 70%ile 기준으로 투찰
        possible_limits = [rp_cand * LOWER_LIMIT_RATE / 100 for rp_cand in possible_rps]
        # 70%ile 하한선 (안전하게)
        safe_limit = possible_limits[int(len(possible_limits) * 0.3)]
        margin_c = 0.1
        price_c = math.floor(safe_limit * (1 + margin_c / 100) / 10) * 10

        if price_c >= lower_limit:
            passes_c += 1
            if price_c <= wp:
                wins_c += 1

    print(f"  대상: {total}건 (복수예비가격 + 낙찰결과 매칭)\n")
    print(f"  {'전략':<30} {'낙찰':>6} {'낙찰률':>8} {'하한통과':>8} {'통과율':>8}")
    print(f"  {'-'*65}")
    print(f"  {'A: 기초금액 기반 (현재)':<30} {wins_a:>5}건 {wins_a/total*100:>7.1f}% {passes_a:>7}건 {passes_a/total*100:>7.1f}%")
    print(f"  {'B: 확률분포 중앙값':<30} {wins_b:>5}건 {wins_b/total*100:>7.1f}% {passes_b:>7}건 {passes_b/total*100:>7.1f}%")
    print(f"  {'C: 확률분포 30%ile 하한선':<27} {wins_c:>5}건 {wins_c/total*100:>7.1f}% {passes_c:>7}건 {passes_c/total*100:>7.1f}%")

    # 전략 C 여유분 조정 실험
    print("\n  [ 전략 C 여유분 조정 실험 ]")
    print(f"  {'percentile':>10} {'margin':>8} {'낙찰':>6} {'낙찰률':>8} {'통과률':>8}")
    print(f"  {'-'*45}")

    for pct in [0.2, 0.3, 0.4, 0.5]:
        for margin_pct in [0.0, 0.1, 0.2, 0.5]:
            w = 0
            p = 0
            for item in prelim_data:
                bid_no = item["bid_no"]
                opening = opening_data.get(bid_no)
                if not opening:
                    continue
                rp = opening.get("reserved_price", 0)
                bp = opening.get("basic_price", 0)
                wp = opening.get("winner_price", 0)
                if rp <= 0 or bp <= 0 or wp <= 0:
                    continue
                prices_list = [pp["price"] for pp in item["preliminary_prices"] if pp["price"] > 0]
                if len(prices_list) < 4:
                    continue

                possible_rps = sorted([sum(c) / 4 for c in combinations(prices_list, 4)])
                possible_limits = [rp_c * LOWER_LIMIT_RATE / 100 for rp_c in possible_rps]
                safe_limit = possible_limits[int(len(possible_limits) * pct)]
                target = math.floor(safe_limit * (1 + margin_pct / 100) / 10) * 10

                lower_limit = rp * LOWER_LIMIT_RATE / 100
                if target >= lower_limit:
                    p += 1
                    if target <= wp:
                        w += 1

            wr = w / total * 100
            pr = p / total * 100
            marker = " ◀" if pr >= 90 and wr > 25 else ""
            print(f"  {pct:>9.0%} {margin_pct:>7.1f}%p {w:>5}건 {wr:>7.1f}% {pr:>7.1f}%{marker}")

    # ===== 4. 실전 활용 가능성 =====
    print(f"\n{'='*60}")
    print("  [4] 실전 활용 가능성")
    print("=" * 60)
    print("""
  복수예비가격 15개는 언제 공개되는가?

  - 입찰 공고 시: 비공개 (입찰 전에는 알 수 없음)
  - 개찰 시: 공개 (개찰과 동시에 추첨, 결과 공개)

  즉, 입찰 전에 15개를 알 수 없으므로 직접 활용은 불가.

  하지만 간접 활용이 가능:
  1. 과거 데이터로 '기초금액 → 15개 예비가격 분포 패턴' 학습
  2. 기초금액만으로 예비가격 범위를 추정
  3. 추정된 범위로 확률분포 기반 투찰가 산출

  핵심: 기초금액 대비 예비가격 분포 패턴이 일관적인가?
""")

    # 기초금액 대비 예비가격 상대 위치 분석
    relative_positions = []  # 각 예비가격의 기초금액 대비 %
    for item in prelim_data:
        bp = item["basic_price"]
        if bp <= 0:
            continue
        for p in item["preliminary_prices"]:
            if p["price"] > 0:
                rel = (p["price"] - bp) / bp * 100
                relative_positions.append(rel)

    if relative_positions:
        avg_rel = sum(relative_positions) / len(relative_positions)
        sorted_rel = sorted(relative_positions)
        min_rel = sorted_rel[0]
        max_rel = sorted_rel[-1]
        p5 = sorted_rel[int(len(sorted_rel) * 0.05)]
        p95 = sorted_rel[int(len(sorted_rel) * 0.95)]
        std_rel = (sum((r - avg_rel) ** 2 for r in relative_positions) / len(relative_positions)) ** 0.5

        print(f"  예비가격의 기초금액 대비 위치 (전체 {len(relative_positions)}개):")
        print(f"    평균: {avg_rel:+.3f}%")
        print(f"    표준편차: {std_rel:.3f}%")
        print(f"    범위: {min_rel:+.3f}% ~ {max_rel:+.3f}%")
        print(f"    5%ile ~ 95%ile: {p5:+.3f}% ~ {p95:+.3f}%")
        print(f"\n  → 기초금액 기준 ±{p95:.1f}% 범위에 90%의 예비가격이 분포")
        print("  → 이 패턴을 학습하면 입찰 전에도 예비가격 범위를 추정 가능")


if __name__ == "__main__":
    main()
