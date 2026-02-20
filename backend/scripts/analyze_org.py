"""
기관별 패턴 분석
- 기관별 예정가격 편차 패턴
- 기관별 낙찰률 패턴
- 상위 기관 최적 파라미터 도출
"""

import json
import math
from pathlib import Path
from collections import defaultdict

DATA_DIR = Path(__file__).parent.parent / "data"
LOWER_LIMIT_RATE = 87.745


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
                all_data.append(item)
    return all_data


def main():
    data = load_all()
    print(f"유효 데이터: {len(data)}건\n")

    # 기관별 분류
    by_org = defaultdict(list)
    for item in data:
        org = item.get("org", "기타")
        by_org[org].append(item)

    # 기관별 통계
    org_stats = []
    for org, items in by_org.items():
        if len(items) < 10:
            continue

        deviations = []
        for item in items:
            bp = item["basic_price"]
            rp = item["reserved_price"]
            dev = (rp - bp) / bp * 100
            deviations.append(dev)

        avg_dev = sum(deviations) / len(deviations)
        std_dev = (sum((d - avg_dev) ** 2 for d in deviations) / len(deviations)) ** 0.5

        org_stats.append({
            "org": org,
            "count": len(items),
            "avg_dev": avg_dev,
            "std_dev": std_dev,
        })

    # 건수 순 정렬
    org_stats.sort(key=lambda x: x["count"], reverse=True)

    print("[ 상위 30개 기관 — 예정가격 오차 패턴 ]")
    print(f"{'기관명':<30} {'건수':>6} {'평균오차':>10} {'표준편차':>10} {'예측가능성':>10}")
    print("-" * 70)

    predictable_orgs = []
    for s in org_stats[:30]:
        predictability = "높음" if s["std_dev"] < 0.5 else ("보통" if s["std_dev"] < 1.0 else "낮음")
        print(f"{s['org'][:28]:<30} {s['count']:>6} {s['avg_dev']:>+9.3f}% {s['std_dev']:>9.3f}% {predictability:>8}")
        if s["std_dev"] < 0.5 and s["count"] >= 20:
            predictable_orgs.append(s)

    # 예측 가능한 기관 (표준편차 < 0.5%)
    print(f"\n[ 예측 가능성 높은 기관 (표준편차 < 0.5%, 20건+) ]: {len(predictable_orgs)}개")
    for s in predictable_orgs:
        print(f"  {s['org'][:35]:<38} {s['count']:>5}건  편차 {s['avg_dev']:+.3f}% ± {s['std_dev']:.3f}%")

    # 기관별 맞춤 전략의 효과 측정
    print(f"\n{'='*60}")
    print("  기관별 맞춤 전략 효과 시뮬레이션")
    print(f"{'='*60}")

    # 기본 전략으로 전체 낙찰률
    default_adj, default_margin = -0.2, 0.9
    total_default_wins = 0
    total_custom_wins = 0
    total_items = 0

    for org, items in by_org.items():
        if len(items) < 10:
            continue

        total_items += len(items)

        # 기본 전략
        default_wins = 0
        for item in items:
            bp = item["basic_price"]
            rp = item["reserved_price"]
            wp = item["winner_price"]
            predicted = bp * (1 + default_adj / 100)
            target_price = math.floor(predicted * (LOWER_LIMIT_RATE + default_margin) / 100 / 10) * 10
            lower_limit = rp * LOWER_LIMIT_RATE / 100
            if target_price >= lower_limit and target_price <= wp:
                default_wins += 1
        total_default_wins += default_wins

        # 맞춤 전략: 기관별 평균 오차를 보정에 반영
        deviations = [(item["reserved_price"] - item["basic_price"]) / item["basic_price"] * 100 for item in items]
        org_avg_dev = sum(deviations) / len(deviations)

        # 기관 오차를 보정에 반영 (기본 보정 + 기관 오차의 절반)
        custom_adj = org_avg_dev * 0.5  # 기관 오차의 절반만 반영 (보수적)
        custom_wins = 0
        custom_passes = 0
        for item in items:
            bp = item["basic_price"]
            rp = item["reserved_price"]
            wp = item["winner_price"]
            predicted = bp * (1 + custom_adj / 100)
            target_price = math.floor(predicted * (LOWER_LIMIT_RATE + default_margin) / 100 / 10) * 10
            lower_limit = rp * LOWER_LIMIT_RATE / 100
            if target_price >= lower_limit:
                custom_passes += 1
                if target_price <= wp:
                    custom_wins += 1
        total_custom_wins += custom_wins

    print(f"\n  10건+ 기관 대상: {total_items}건")
    print(f"  기본 전략 낙찰: {total_default_wins}건 ({total_default_wins/total_items*100:.1f}%)")
    print(f"  맞춤 전략 낙찰: {total_custom_wins}건 ({total_custom_wins/total_items*100:.1f}%)")
    print(f"  차이: {total_custom_wins - total_default_wins:+d}건 ({(total_custom_wins - total_default_wins)/total_items*100:+.2f}%p)")

    # 더 정교한 기관별 전략: 기관별 그리드서치 (표본 20건+ 기관만)
    print(f"\n{'='*60}")
    print("  기관별 그리드 서치 (20건+ 기관)")
    print(f"{'='*60}")

    custom_total_wins = 0
    custom_total_items = 0
    orgs_with_custom = 0

    for org, items in sorted(by_org.items(), key=lambda x: len(x[1]), reverse=True):
        if len(items) < 20:
            continue

        orgs_with_custom += 1
        custom_total_items += len(items)

        best_wins = 0

        for adj_x10 in range(-10, 16):
            adj = adj_x10 / 10
            for margin_x10 in range(0, 16):
                margin = margin_x10 / 10
                wins = 0
                passes = 0

                for item in items:
                    bp = item["basic_price"]
                    rp = item["reserved_price"]
                    wp = item["winner_price"]
                    predicted = bp * (1 + adj / 100)
                    target_price = math.floor(predicted * (LOWER_LIMIT_RATE + margin) / 100 / 10) * 10
                    lower_limit = rp * LOWER_LIMIT_RATE / 100
                    if target_price >= lower_limit:
                        passes += 1
                        if target_price <= wp:
                            wins += 1

                pr = passes / len(items) * 100
                if pr >= 85.0 and wins > best_wins:
                    best_wins = wins

        custom_total_wins += best_wins

    if custom_total_items > 0:
        default_for_custom = 0
        for org, items in by_org.items():
            if len(items) < 20:
                continue
            for item in items:
                bp = item["basic_price"]
                rp = item["reserved_price"]
                wp = item["winner_price"]
                predicted = bp * (1 + default_adj / 100)
                target_price = math.floor(predicted * (LOWER_LIMIT_RATE + default_margin) / 100 / 10) * 10
                lower_limit = rp * LOWER_LIMIT_RATE / 100
                if target_price >= lower_limit and target_price <= wp:
                    default_for_custom += 1

        print(f"\n  20건+ 기관: {orgs_with_custom}개, {custom_total_items}건")
        print(f"  기본 전략: {default_for_custom}건 ({default_for_custom/custom_total_items*100:.1f}%)")
        print(f"  기관별 최적: {custom_total_wins}건 ({custom_total_wins/custom_total_items*100:.1f}%)")
        print(f"  이론적 상한: +{custom_total_wins - default_for_custom}건 ({(custom_total_wins - default_for_custom)/custom_total_items*100:+.2f}%p)")
        print("  (주의: 과적합 가능 — 실전 효과는 이보다 낮을 것)")


if __name__ == "__main__":
    main()
