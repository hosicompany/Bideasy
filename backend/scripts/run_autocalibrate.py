"""
자가보정 사이클 CLI
====================
입찰가 산정 파라미터를 자동 재최적화하고 가드 검증 후 채택/롤백한다.

사용법:
    python scripts/run_autocalibrate.py              # 정식 실행 (채택 시 active 교체)
    python scripts/run_autocalibrate.py --dry-run    # 후보 생성·검증만, 저장소 불변
    python scripts/run_autocalibrate.py --force      # 새 데이터 없어도 강제 실행
    python scripts/run_autocalibrate.py --tau 0.05 --lam 0.5   # 하이퍼파라미터 오버라이드

내부 검증·운영용 — 사용자에게 노출되지 않음.
"""

import argparse
import sys
from pathlib import Path

# Windows 콘솔 한글 깨짐 방지
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

sys.path.insert(0, str(Path(__file__).parent.parent))
from app.services.autocalibrate.loop import run_calibration_cycle


def main():
    parser = argparse.ArgumentParser(description="BidEasy 자가보정 사이클")
    parser.add_argument("--dry-run", action="store_true", help="후보 생성·검증만 (저장소 불변)")
    parser.add_argument("--force", action="store_true", help="새 데이터 없어도 강제 실행")
    parser.add_argument("--lam", type=float, default=None, help="연속 위험 패널티 계수 λ")
    parser.add_argument("--gamma", type=float, default=None, help="목표 초과 패널티 계수 γ")
    parser.add_argument("--tau", type=float, default=None, help="목표 탈락률 τ")
    parser.add_argument("--eta", type=float, default=None, help="변화 억제 정규화 계수 η")
    args = parser.parse_args()

    objective_kwargs = {}
    if args.lam is not None:
        objective_kwargs["lam"] = args.lam
    if args.gamma is not None:
        objective_kwargs["gamma"] = args.gamma
    if args.tau is not None:
        objective_kwargs["tau"] = args.tau
    if args.eta is not None:
        objective_kwargs["eta"] = args.eta

    trigger = "manual" if args.force else "scheduled"

    print("=" * 64)
    print("  BidEasy 자가보정 사이클")
    print(f"  모드: {'DRY-RUN' if args.dry_run else '정식 실행'}"
          f" | 트리거: {trigger}")
    if objective_kwargs:
        print(f"  하이퍼파라미터 오버라이드: {objective_kwargs}")
    print("=" * 64)

    report = run_calibration_cycle(
        trigger=trigger, dry_run=args.dry_run, **objective_kwargs
    )

    print()
    if report.skipped:
        print(f"[건너뜀] {report.reason}")
        return

    print(f"기준선 버전: {report.baseline_version}")
    print(f"후보 버전:   {report.candidate_version}")
    print(f"적응형 연도 가중치: {report.year_weights}")
    print()

    d = report.decision
    print("[ 지표 변화 (후보 vs 기준선) ]")
    print(f"  낙찰률:     {d.baseline_metrics['win_rate']}% → "
          f"{d.insample_metrics['win_rate']}% "
          f"({report.decision.metric_deltas['win_rate']:+.2f}%p)")
    print(f"  탈락률:     {d.baseline_metrics['dropout_rate']}% → "
          f"{d.insample_metrics['dropout_rate']}% "
          f"({report.decision.metric_deltas['dropout_rate']:+.2f}%p)")
    print(f"  사정률오차: {d.baseline_metrics['rate_error']}%p → "
          f"{d.insample_metrics['rate_error']}%p "
          f"({report.decision.metric_deltas['rate_error']:+.4f}%p)")
    if d.holdout_metrics:
        print(f"  [hold-out] 탈락률: {d.baseline_holdout.get('dropout_rate')}% → "
              f"{d.holdout_metrics.get('dropout_rate')}%")
    print(f"  위험모델 캘리브레이션 오차: {report.risk_calibration_error*100:.3f}%p")
    print()

    print("[ 가드 판정 ]")
    for reason in d.reasons:
        print(f"  {reason}")
    print()

    status = "DRY-RUN (저장 안 함)" if report.dry_run else (
        "✓ 채택됨 — active 교체" if report.adopted else "✗ 거부됨 — active 불변 (자동 롤백)"
    )
    print(f"결과: {status}")
    print("=" * 64)


if __name__ == "__main__":
    main()
