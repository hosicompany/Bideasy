"""
모의 투찰 시뮬레이션
BidEasy 알고리즘 vs 실제 낙찰 결과 비교 분석

분석 내용:
1. 우리 알고리즘이 추천하는 투찰가 vs 실제 낙찰가 비교
2. 하한선 미달 건수 (탈락 여부)
3. 낙찰률 분포 분석
4. 금액대별 성과 분석
"""

import json
import sys
from pathlib import Path
from dataclasses import dataclass

# calculator.py 경로 추가
sys.path.insert(0, str(Path(__file__).parent.parent))
from app.services.calculator import CalculatorService


@dataclass
class SimulationResult:
    """개별 건 시뮬레이션 결과"""
    bid_no: str
    title: str
    org: str
    basic_price: float
    estimated_price: float
    reserved_price: float
    # 실제 결과
    actual_winner_price: float
    actual_winner_rate: float
    actual_lower_limit_rate: float
    # 우리 알고리즘 결과
    our_bid_price: int
    our_bid_rate: float
    our_safety: str
    # 비교
    price_diff: float          # 우리 투찰가 - 실제 낙찰가
    rate_diff: float           # 우리 투찰률 - 실제 낙찰률
    would_win: bool            # 우리가 낙찰 가능했는지
    above_lower_limit: bool    # 하한선 이상인지


def load_data(data_dir: Path) -> list:
    """연도별 JSON 파일 로드"""
    all_data = []
    for year in range(2021, 2027):
        f = data_dir / f"opening_results_{year}.json"
        if f.exists():
            with open(f) as fh:
                items = json.load(fh)
                all_data.extend(items)
                print(f"  [{year}] {len(items)}건 로드")
    return all_data


def simulate_single(item: dict, strategy_rate: float = None) -> SimulationResult:
    """
    단일 건 시뮬레이션

    strategy_rate: 사정률 (None이면 하한선 근처 안전 전략)
    """
    basic_price = item["basic_price"]
    actual_lower_limit = item.get("lower_limit_rate", 87.745)

    if basic_price <= 0:
        return None

    reserved_price = item.get("reserved_price", 0)

    # 예정가격이 있으면 예정가격 기준, 없으면 기초금액 기준
    price_base = reserved_price if reserved_price > 0 else basic_price

    if strategy_rate is None:
        # 기본 전략: 예정가격 * 하한율 바로 위
        target_price = price_base * (actual_lower_limit / 100) + 10
        our_price = CalculatorService.truncate_to_10_won(target_price)
    else:
        # 사정률 전략: 기초금액 기준 계산
        calc_result = CalculatorService.calculate_detailed_bid(
            basic_price=basic_price,
            rate=strategy_rate,
            contract_type="CONSTRUCTION",
            a_value=0
        )
        our_price = calc_result.result_price

    our_rate = (our_price / basic_price) * 100 if basic_price > 0 else 0

    # 하한선 금액 (예정가격 기준 — 실제 제도와 동일)
    lower_limit_price = price_base * (actual_lower_limit / 100)
    above_limit = our_price >= lower_limit_price

    actual_winner_price = item.get("winner_price", 0)
    actual_winner_rate = item.get("winner_rate", 0)

    # 낙찰 가능 여부: 하한선 이상이고, 실제 낙찰가보다 낮으면 낙찰
    # (최저가 낙찰제: 하한선 이상 중 최저가가 낙찰)
    would_win = above_limit and our_price <= actual_winner_price

    return SimulationResult(
        bid_no=item["bid_no"],
        title=item.get("title", ""),
        org=item.get("org", ""),
        basic_price=basic_price,
        estimated_price=item.get("estimated_price", 0),
        reserved_price=reserved_price,
        actual_winner_price=actual_winner_price,
        actual_winner_rate=actual_winner_rate,
        actual_lower_limit_rate=actual_lower_limit,
        our_bid_price=our_price,
        our_bid_rate=round(our_rate, 4),
        our_safety="SAFE" if above_limit else "DANGER",
        price_diff=our_price - actual_winner_price,
        rate_diff=round(our_rate - actual_winner_rate, 4),
        would_win=would_win,
        above_lower_limit=above_limit,
    )


def run_simulation(data: list, strategy_name: str, strategy_rate: float = None) -> dict:
    """전체 시뮬레이션 실행"""
    results = []
    skipped = 0

    for item in data:
        r = simulate_single(item, strategy_rate)
        if r is None:
            skipped += 1
            continue
        results.append(r)

    if not results:
        return {"error": "데이터 없음"}

    # 통계 계산
    total = len(results)
    wins = sum(1 for r in results if r.would_win)
    above_limit = sum(1 for r in results if r.above_lower_limit)
    below_limit = total - above_limit

    rate_diffs = [r.rate_diff for r in results]
    price_diffs = [r.price_diff for r in results]
    our_rates = [r.our_bid_rate for r in results]
    actual_rates = [r.actual_winner_rate for r in results]

    # 금액대별 분석
    brackets = {
        "1억 미만": [],
        "1~5억": [],
        "5~10억": [],
        "10~50억": [],
        "50억 이상": [],
    }
    for r in results:
        bp = r.basic_price
        if bp < 1e8:
            brackets["1억 미만"].append(r)
        elif bp < 5e8:
            brackets["1~5억"].append(r)
        elif bp < 1e9:
            brackets["5~10억"].append(r)
        elif bp < 5e9:
            brackets["10~50억"].append(r)
        else:
            brackets["50억 이상"].append(r)

    bracket_stats = {}
    for name, items in brackets.items():
        if items:
            bracket_stats[name] = {
                "count": len(items),
                "win_rate_pct": round(sum(1 for r in items if r.would_win) / len(items) * 100, 1),
                "avg_rate_diff": round(sum(r.rate_diff for r in items) / len(items), 4),
                "above_limit_pct": round(sum(1 for r in items if r.above_lower_limit) / len(items) * 100, 1),
            }

    stats = {
        "strategy": strategy_name,
        "total": total,
        "skipped": skipped,
        "wins": wins,
        "win_rate_pct": round(wins / total * 100, 2),
        "above_limit": above_limit,
        "below_limit": below_limit,
        "below_limit_pct": round(below_limit / total * 100, 2),
        "our_avg_rate": round(sum(our_rates) / total, 4),
        "actual_avg_rate": round(sum(actual_rates) / total, 4),
        "avg_rate_diff": round(sum(rate_diffs) / total, 4),
        "avg_price_diff": round(sum(price_diffs) / total),
        "rate_diff_min": round(min(rate_diffs), 4),
        "rate_diff_max": round(max(rate_diffs), 4),
        "bracket_analysis": bracket_stats,
    }

    return stats


def print_stats(stats: dict):
    """결과 출력"""
    print(f"\n{'='*60}")
    print(f"전략: {stats['strategy']}")
    print(f"{'='*60}")
    print(f"총 분석 건수: {stats['total']:,}건 (스킵: {stats['skipped']}건)")
    print("\n--- 핵심 지표 ---")
    print(f"낙찰 성공률: {stats['win_rate_pct']}% ({stats['wins']:,}건/{stats['total']:,}건)")
    print(f"하한선 통과율: {100 - stats['below_limit_pct']}% (미달: {stats['below_limit']}건)")
    print("\n--- 투찰률 분석 ---")
    print(f"우리 평균 투찰률: {stats['our_avg_rate']}%")
    print(f"실제 평균 낙찰률: {stats['actual_avg_rate']}%")
    print(f"평균 차이: {stats['avg_rate_diff']}%p")
    print(f"차이 범위: {stats['rate_diff_min']}%p ~ {stats['rate_diff_max']}%p")
    print("\n--- 금액대별 분석 ---")
    for name, bs in stats.get("bracket_analysis", {}).items():
        print(f"  {name}: {bs['count']}건, 낙찰률 {bs['win_rate_pct']}%, "
              f"하한통과 {bs['above_limit_pct']}%, 평균차이 {bs['avg_rate_diff']}%p")


def main():
    data_dir = Path(__file__).parent.parent / "data"

    print("=" * 60)
    print("BidEasy 모의 투찰 시뮬레이션")
    print("=" * 60)

    # 데이터 로드
    print("\n데이터 로드 중...")
    data = load_data(data_dir)

    if not data:
        print("데이터가 없습니다. 크롤링 완료 후 다시 실행하세요.")
        return

    print(f"\n총 {len(data):,}건 로드 완료")

    # 유효 데이터 필터 (기초금액 > 0, 낙찰가 > 0)
    valid = [d for d in data if d.get("basic_price", 0) > 0 and d.get("winner_price", 0) > 0]
    print(f"유효 데이터: {len(valid):,}건")

    # 전략별 시뮬레이션
    strategies = [
        ("전략1: 하한선 +0.001%", None),        # 기본 전략 (하한선 바로 위)
        ("전략2: -12.0% (보수적)", -12.0),       # 기초금액의 88% (하한선 약간 위)
        ("전략3: -11.5% (중도)", -11.5),         # 기초금액의 88.5%
        ("전략4: -11.0% (적극적)", -11.0),       # 기초금액의 89%
        ("전략5: -10.0% (공격적)", -10.0),       # 기초금액의 90%
    ]

    all_stats = []
    for name, rate in strategies:
        stats = run_simulation(valid, name, rate)
        print_stats(stats)
        all_stats.append(stats)

    # 결과 저장
    output_file = data_dir / "simulation_results.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(all_stats, f, ensure_ascii=False, indent=2)
    print(f"\n결과 저장: {output_file}")

    # 요약
    print(f"\n{'='*60}")
    print("전략별 비교 요약")
    print(f"{'='*60}")
    print(f"{'전략':<30} {'낙찰률':>8} {'하한통과':>8} {'평균차이':>10}")
    print("-" * 60)
    for s in all_stats:
        print(f"{s['strategy']:<30} {s['win_rate_pct']:>7}% {100-s['below_limit_pct']:>7}% {s['avg_rate_diff']:>9}%p")


if __name__ == "__main__":
    main()
