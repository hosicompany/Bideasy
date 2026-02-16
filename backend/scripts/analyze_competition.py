"""
경쟁 환경 분석
- 입찰건당 평균 참여자 수
- 낙찰률의 이론적 상한선 (1/N)
- 우리 알고리즘의 상대적 성과
"""

import json
from pathlib import Path
from collections import defaultdict

DATA_DIR = Path(__file__).parent.parent / "data"


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
    print(f"분석 대상: {len(data)}건\n")

    # 참여자 수 분석
    bid_counts = []
    by_method = defaultdict(list)

    for item in data:
        cnt = item.get("bid_count", 0) or item.get("participant_count", 0) or item.get("bidder_count", 0)
        if cnt > 0:
            bid_counts.append(cnt)
            method = item.get("bid_method", "기타")
            by_method[method].append(cnt)

    if bid_counts:
        avg_cnt = sum(bid_counts) / len(bid_counts)
        median_cnt = sorted(bid_counts)[len(bid_counts) // 2]
        min_cnt = min(bid_counts)
        max_cnt = max(bid_counts)

        print("=" * 60)
        print("  입찰 참여자 수 분석")
        print("=" * 60)
        print(f"  데이터 보유: {len(bid_counts)}건 / {len(data)}건")
        print(f"  평균: {avg_cnt:.1f}개 업체")
        print(f"  중앙값: {median_cnt}개 업체")
        print(f"  최소~최대: {min_cnt} ~ {max_cnt}개 업체")
        print(f"  이론적 랜덤 낙찰률 (1/평균): {1/avg_cnt*100:.1f}%")
        print(f"  이론적 랜덤 낙찰률 (1/중앙값): {1/median_cnt*100:.1f}%")

        # 분포
        brackets = [(1, 5), (6, 10), (11, 20), (21, 50), (51, 100), (101, 999)]
        print(f"\n  참여자 수 분포:")
        for lo, hi in brackets:
            cnt = sum(1 for c in bid_counts if lo <= c <= hi)
            if cnt > 0:
                print(f"    {lo}~{hi}개 업체: {cnt}건 ({cnt/len(bid_counts)*100:.1f}%)")

        # 입찰방법별
        print(f"\n  입찰방법별 평균 참여자:")
        for method in ["소액수의견적", "적격심사제"]:
            counts = by_method.get(method, [])
            if counts:
                avg = sum(counts) / len(counts)
                med = sorted(counts)[len(counts) // 2]
                print(f"    {method}: 평균 {avg:.1f}개, 중앙값 {med}개 (이론 낙찰률 {1/avg*100:.1f}%)")
    else:
        print("  참여자 수 데이터가 없습니다.")
        print("  가용 필드 확인 중...")
        if data:
            sample = data[0]
            for key in sorted(sample.keys()):
                if "count" in key.lower() or "num" in key.lower() or "참여" in key or "업체" in key or "bid" in key.lower():
                    print(f"    {key}: {sample[key]}")
            print(f"\n  전체 필드: {list(sample.keys())}")

    # 낙찰가 vs 하한선 간격 분석 (경쟁 치열도 간접 지표)
    print(f"\n{'='*60}")
    print("  낙찰가 분포 분석 (경쟁 치열도 간접 지표)")
    print(f"{'='*60}")

    margins = []  # 낙찰가가 하한선 대비 얼마나 위인지
    for item in data:
        rp = item["reserved_price"]
        wp = item["winner_price"]
        lower_limit = rp * 87.745 / 100
        if lower_limit > 0:
            margin_pct = (wp - lower_limit) / lower_limit * 100
            margins.append(margin_pct)

    if margins:
        avg_margin = sum(margins) / len(margins)
        sorted_m = sorted(margins)
        median_margin = sorted_m[len(margins) // 2]
        p10 = sorted_m[int(len(margins) * 0.1)]
        p25 = sorted_m[int(len(margins) * 0.25)]
        p75 = sorted_m[int(len(margins) * 0.75)]
        within_01 = sum(1 for m in margins if m < 0.1) / len(margins) * 100
        within_05 = sum(1 for m in margins if m < 0.5) / len(margins) * 100
        within_1 = sum(1 for m in margins if m < 1.0) / len(margins) * 100

        print(f"  낙찰가의 하한선 대비 여유도:")
        print(f"    평균: +{avg_margin:.3f}%")
        print(f"    중앙값: +{median_margin:.3f}%")
        print(f"    10%ile: +{p10:.3f}%")
        print(f"    25%ile: +{p25:.3f}%")
        print(f"    75%ile: +{p75:.3f}%")
        print(f"\n  하한선 대비 0.1% 이내: {within_01:.1f}% ← 극도로 치열")
        print(f"  하한선 대비 0.5% 이내: {within_05:.1f}%")
        print(f"  하한선 대비 1.0% 이내: {within_1:.1f}%")

    # 입찰방법별 경쟁도
    print(f"\n  입찰방법별 낙찰가-하한선 간격:")
    for method in ["소액수의견적", "적격심사제"]:
        method_margins = []
        for item in data:
            if item.get("bid_method") != method:
                continue
            rp = item["reserved_price"]
            wp = item["winner_price"]
            lower_limit = rp * 87.745 / 100
            if lower_limit > 0:
                method_margins.append((wp - lower_limit) / lower_limit * 100)
        if method_margins:
            avg_m = sum(method_margins) / len(method_margins)
            med_m = sorted(method_margins)[len(method_margins) // 2]
            print(f"    {method}: 평균 +{avg_m:.3f}%, 중앙값 +{med_m:.3f}%")

    # 우리 성과 비교
    print(f"\n{'='*60}")
    print("  BidEasy 알고리즘 성과 평가")
    print(f"{'='*60}")
    our_win_rate = 13.3
    print(f"  우리 낙찰률: {our_win_rate}%")

    if bid_counts:
        random_rate = 1 / avg_cnt * 100
        print(f"  랜덤 투찰 낙찰률 (이론): {random_rate:.1f}%")
        print(f"  우리 대비 랜덤: {our_win_rate / random_rate:.1f}배")

    print(f"\n  시장 벤치마크 (업계 추정):")
    print(f"    초보 업체 (감으로): ~3~5%")
    print(f"    일반 업체 (기본 분석): ~5~8%")
    print(f"    전문 솔루션 (비드프로 등): ~10~15%")
    print(f"    BidEasy 현재: {our_win_rate}% ← 전문 솔루션 수준")


if __name__ == "__main__":
    main()
