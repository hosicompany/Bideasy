"""
모델 정확도 통합 리포트 (정기 실행용)
=====================================
모델/알고리즘을 수정할 때마다 이 스크립트를 실행하면:
  1. 백테스트 (종료된 입찰건에 모의 투찰 → 실제와 비교)
  2. 세그먼트 분석 (입찰방법별 / 금액대별 강·약점)
  3. 몬테카를로 시뮬레이션 검증 (예정가격 예측 정확도)
  4. 핵심 지표를 data/accuracy_history.jsonl 에 누적 기록
  5. 직전 실행 대비 변화량(delta) 표시 → 모델 수정이 개선인지 악화인지 즉시 확인

사용법:
    python scripts/model_accuracy_report.py

내부 검증용 — 사용자에게 노출되지 않음.
"""

import json
import sys
import statistics
import subprocess
from collections import defaultdict
from datetime import datetime
from pathlib import Path

# Windows 콘솔 한글 깨짐 방지
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"
HISTORY_FILE = DATA_DIR / "accuracy_history.jsonl"

sys.path.insert(0, str(BASE_DIR))


def run_backtest() -> dict:
    """mock_bidding_test.py 실행 후 결과 JSON 로드."""
    print("[1/3] 백테스트 실행 중 (종료된 입찰건 모의 투찰)...")
    result = subprocess.run(
        [sys.executable, str(BASE_DIR / "scripts" / "mock_bidding_test.py")],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        print("  ⚠ 백테스트 실행 실패:")
        print(result.stderr[-500:])
        sys.exit(1)
    with open(DATA_DIR / "mock_test_results.json", encoding="utf-8") as f:
        return json.load(f)


def analyze_segments(details: list) -> dict:
    """입찰방법별 / 금액대별 정확도 분석."""

    def seg_stats(items):
        n = len(items)
        if n == 0:
            return None
        wins = sum(1 for x in items if x.get("won"))
        passed = sum(1 for x in items if x.get("passed_limit"))
        gaps = [
            abs(x["our_rate"] - x["real_winner_rate"])
            for x in items
            if "our_rate" in x and "real_winner_rate" in x
        ]
        return {
            "n": n,
            "win_rate": round(wins / n * 100, 2),
            "pass_rate": round(passed / n * 100, 2),
            "rate_error": round(statistics.mean(gaps), 4) if gaps else 0,
        }

    by_method = defaultdict(list)
    for x in details:
        by_method[x.get("bid_method", "(미상)")].append(x)

    def tier(p):
        if p < 1e7:
            return "1천만원 미만"
        if p < 5e7:
            return "1천만~5천만"
        if p < 1e8:
            return "5천만~1억"
        if p < 5e8:
            return "1억~5억"
        return "5억 이상"

    by_tier = defaultdict(list)
    for x in details:
        by_tier[tier(x.get("basic_price", 0))].append(x)

    return {
        "by_method": {m: seg_stats(v) for m, v in by_method.items() if len(v) >= 10},
        "by_tier": {t: seg_stats(v) for t, v in by_tier.items()},
    }


def verify_monte_carlo(sample_size: int = 200) -> dict:
    """종료된 입찰건으로 몬테카를로 예정가격 예측 정확도 검증."""
    print("[2/3] 몬테카를로 시뮬레이션 검증 중...")
    from app.services.simulation_service import BidSimulationService

    svc = BidSimulationService()
    bids = []
    for year in (2025, 2024, 2023):
        f = DATA_DIR / f"opening_results_{year}.json"
        if f.exists():
            with open(f, encoding="utf-8") as fh:
                bids.extend(json.load(fh))
        if len(bids) >= sample_size * 2:
            break

    valid = [b for b in bids if b.get("basic_price") and b.get("reserved_price")][:sample_size]
    in_range = 0
    errors = []
    for b in valid:
        mc = svc.run_monte_carlo(base_amount=b["basic_price"], num_simulations=2000)
        lo, hi = mc.get("percentile_5"), mc.get("percentile_95")
        actual = b["reserved_price"]
        if lo and hi and lo <= actual <= hi:
            in_range += 1
        if mc.get("mean"):
            errors.append(abs(mc["mean"] - actual) / actual * 100)

    return {
        "sample": len(valid),
        "in_range_pct": round(in_range / len(valid) * 100, 2) if valid else 0,
        "mean_error_pct": round(statistics.mean(errors), 4) if errors else 0,
    }


def print_report(summary: dict, segments: dict, prev: dict | None):
    """리포트 출력 + 직전 대비 delta."""

    def delta(key, cur, fmt="{:+.2f}"):
        if not prev or key not in prev:
            return ""
        diff = cur - prev[key]
        if abs(diff) < 1e-9:
            return "  (변화 없음)"
        arrow = "▲" if diff > 0 else "▼"
        return f"  {arrow} {fmt.format(diff)} (직전 대비)"

    print()
    print("=" * 64)
    print("  BidEasy 모델 정확도 통합 리포트")
    print(f"  실행: {summary['timestamp']}")
    print("=" * 64)
    print()
    print("[ 백테스트 — 종료된 입찰건 모의 투찰 ]")
    print(f"  총 문항: {summary['total']}건")
    print(f"  낙찰률: {summary['win_rate']}%{delta('win_rate', summary['win_rate'])}")
    print(
        f"  하한선 통과율: {summary['pass_rate']}%"
        f"{delta('pass_rate', summary['pass_rate'])}"
    )
    print(
        f"  사정률 평균 오차: {summary['rate_error']}%p"
        f"{delta('rate_error', summary['rate_error'], '{:+.4f}')}"
    )
    print()
    print("[ 몬테카를로 시뮬레이션 검증 ]")
    print(
        f"  예정가격 예측 적중률(5~95% 범위): {summary['mc_in_range_pct']}%"
        f"{delta('mc_in_range_pct', summary['mc_in_range_pct'])}"
    )
    print(
        f"  예측 중심값 오차: {summary['mc_mean_error_pct']}%"
        f"{delta('mc_mean_error_pct', summary['mc_mean_error_pct'], '{:+.4f}')}"
    )
    print()
    print("[ 입찰방법별 강·약점 ]")
    print(f"  {'입찰방법':<22}{'문항':>6}{'낙찰률':>8}{'사정률오차':>12}")
    print("  " + "-" * 48)
    for m, s in sorted(
        segments["by_method"].items(), key=lambda kv: -kv[1]["n"]
    ):
        print(
            f"  {m:<22}{s['n']:>6}{s['win_rate']:>7.1f}%{s['rate_error']:>10.3f}%p"
        )
    print()
    print("[ 금액대별 ]")
    order = ["1천만원 미만", "1천만~5천만", "5천만~1억", "1억~5억", "5억 이상"]
    print(f"  {'금액대':<16}{'문항':>6}{'낙찰률':>8}{'사정률오차':>12}")
    print("  " + "-" * 44)
    for t in order:
        if t in segments["by_tier"]:
            s = segments["by_tier"][t]
            print(
                f"  {t:<16}{s['n']:>6}{s['win_rate']:>7.1f}%{s['rate_error']:>10.3f}%p"
            )
    print()
    print(f"  📁 이력 기록: {HISTORY_FILE}")
    if prev:
        print(f"  📊 직전 실행: {prev.get('timestamp', '?')}")
    print("=" * 64)


def main():
    backtest = run_backtest()
    details = backtest["details"]

    gaps = [
        abs(x["our_rate"] - x["real_winner_rate"])
        for x in details
        if "our_rate" in x and "real_winner_rate" in x
    ]
    segments = analyze_segments(details)
    mc = verify_monte_carlo()

    summary = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total": backtest["total"],
        "win_rate": backtest["win_rate"],
        "pass_rate": round(backtest["passed_limit"] / backtest["total"] * 100, 2),
        "rate_error": round(statistics.mean(gaps), 4) if gaps else 0,
        "mc_sample": mc["sample"],
        "mc_in_range_pct": mc["in_range_pct"],
        "mc_mean_error_pct": mc["mean_error_pct"],
    }

    # 직전 기록 로드 (delta 비교용)
    prev = None
    if HISTORY_FILE.exists():
        lines = HISTORY_FILE.read_text(encoding="utf-8").strip().splitlines()
        if lines:
            prev = json.loads(lines[-1])

    print("[3/3] 리포트 생성...")
    print_report(summary, segments, prev)

    # 이력에 누적 기록
    with open(HISTORY_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(summary, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
