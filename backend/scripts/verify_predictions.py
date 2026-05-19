"""
예측 검증 CLI — 수동 실행 진입점
================================
일상적 자동 실행은 Celery beat 가 담당 (app/tasks/verification_tasks.py).
본 CLI 는 수동 점검·디버깅용.

사용법:
  docker compose ... exec app python scripts/verify_predictions.py
  docker compose ... exec app python scripts/verify_predictions.py --bid-no R26BK...
  docker compose ... exec app python scripts/verify_predictions.py --days 7 --no-save
"""

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

# 백엔드 모듈 path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import models
from app.db.session import SessionLocal
from app.services.prediction_verifier import verify_notices

LOG_PATH = Path(__file__).resolve().parent.parent / "data" / "predictions_log.jsonl"


def main():
    parser = argparse.ArgumentParser(description="예측 vs 실 결과 검증 (CLI)")
    parser.add_argument("--bid-no", help="특정 공고 1건만 검증")
    parser.add_argument("--days", type=int, default=30, help="최근 N일 (기본 30)")
    parser.add_argument("--limit", type=int, default=200, help="최대 건수 (기본 200)")
    parser.add_argument("--no-save", action="store_true", help="JSONL 저장 안 함 (드라이런)")
    args = parser.parse_args()

    db = SessionLocal()
    now = datetime.now()
    try:
        if args.bid_no:
            notices = db.query(models.Notice).filter(
                models.Notice.bid_no == args.bid_no
            ).all()
        else:
            cutoff = now - timedelta(days=args.days)
            notices = db.query(models.Notice).filter(
                models.Notice.end_date < now,
                models.Notice.end_date > cutoff,
            ).limit(args.limit).all()

        print(f"검증 대상: {len(notices)}건")
        if not notices:
            return

        log_path = None if args.no_save else LOG_PATH
        summary = verify_notices(db, notices, log_path=log_path)

        # 개별 결과 출력
        for r in summary["results"]:
            bid_no = r["bid_no"]
            title = (r.get("title") or "")[:50]
            status = r["status"]
            if status == "VERIFIED":
                std = r["standard"]
                auto = r["auto_recommended"]
                agg = r["aggressive_mc"]
                print(f"[{status}] {bid_no} {title}")
                print(f"  표준  {std['result']:7s} {std['diff_pct']:+7.2f}%  "
                      f"자동 {auto['result']:7s} {auto['diff_pct']:+7.2f}%  "
                      f"공격 {agg['result']:7s} {agg['diff_pct']:+7.2f}%")
            elif status == "PENDING":
                print(f"[{status}] {bid_no} {title}  ({r.get('reason', '')})")
            else:
                print(f"[{status}] {bid_no} {title}  {r.get('error', '')}")

        # 집계
        print()
        print("=" * 60)
        print("  집계")
        print("=" * 60)
        print(f"  검증 완료: {summary['verified']}건  /  대기: {summary['pending']}  /  에러: {summary['errors']}")
        if summary["verified"] > 0:
            n = summary["verified"]
            for label, stats in summary["policies"].items():
                w = stats["wins"]
                d = stats["dropouts"]
                print(f"  [{label:<22}]  낙찰 {w:>4} ({w/n*100:>4.1f}%)   탈락 {d:>4} ({d/n*100:>4.1f}%)")
        if not args.no_save and summary["results"]:
            print(f"\n  → {LOG_PATH} 에 {len(summary['results'])}건 누적")
    finally:
        db.close()


if __name__ == "__main__":
    main()
