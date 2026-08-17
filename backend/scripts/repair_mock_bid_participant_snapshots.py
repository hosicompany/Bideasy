"""모의투찰 최종 참가자 스냅샷을 API 정본으로 재수집하고 가상 순위를 재백필한다.

기본 실행은 조회 계획만 출력한다. ``--commit`` 을 줄 때만 공공 API 재조회와
운영 DB 쓰기를 수행한다.

배경
----
참가자 재크롤을 계속 병합만 하면 이전 응답의 유령 행이 남아 서로 다른
시점의 ``opengRank`` 가 한 공고에 섞인다. 2026-08-17 운영 실측에서 최근
300공고의 17.708% 가 이 형태로 어긋났다. 수정된 크롤러는 낙찰자 확정 후
응답을 최종 스냅샷으로 동기화하므로, 이 스크립트가 기존 확정분의
개찰일을 다시 조회해 복구 경로를 연다.

예시
----
    python scripts/repair_mock_bid_participant_snapshots.py
    python scripts/repair_mock_bid_participant_snapshots.py --days-back 30 --commit
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db import models
from app.db.session import SessionLocal
from app.services.mock_bidding import backfill_participant_ranks, rank_axis_health
from app.services.opening_result_crawler import crawl_recent_openings, windows_for_dates


def _completed_opening_dates(days_back: int) -> list:
    """모의투찰 중 낙찰결과가 확정된 공고의 개찰일만 고른다."""
    cutoff = datetime.now() - timedelta(days=days_back)
    db = SessionLocal()
    try:
        rows = (
            db.query(models.OpeningResult.open_date)
            .join(
                models.MockBid,
                models.MockBid.bid_no == models.OpeningResult.bid_no,
            )
            .filter(
                models.OpeningResult.open_date.isnot(None),
                models.OpeningResult.open_date >= cutoff,
                models.OpeningResult.winner_price.isnot(None),
                models.OpeningResult.winner_price > 0,
            )
            .distinct()
            .all()
        )
        return sorted({value.date() for (value,) in rows if value is not None})
    finally:
        db.close()


def _health() -> dict:
    db = SessionLocal()
    try:
        return rank_axis_health(db)
    finally:
        db.close()


def _backfill(limit: int, max_batches: int) -> dict:
    db = SessionLocal()
    batches = 0
    candidates = 0
    backfilled = 0
    complete = False
    last_candidates = 0
    try:
        for _ in range(max_batches):
            result = backfill_participant_ranks(db, limit=limit)
            batches += 1
            last_candidates = int(result.get("candidates") or 0)
            candidates += last_candidates
            backfilled += int(result.get("backfilled") or 0)
            if not last_candidates:
                complete = True
                break
            if not result.get("backfilled"):
                break
        return {
            "batches": batches,
            "candidates": candidates,
            "backfilled": backfilled,
            "last_candidates": last_candidates,
            "complete": complete,
        }
    finally:
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="모의투찰 최종 참가자 스냅샷과 가상 순위 복구",
    )
    parser.add_argument("--days-back", type=int, default=30)
    parser.add_argument("--max-pages", type=int, default=250)
    parser.add_argument("--backfill-limit", type=int, default=5000)
    parser.add_argument("--max-backfill-batches", type=int, default=20)
    parser.add_argument(
        "--commit",
        action="store_true",
        help="공공 API 재조회·DB 스냅샷 동기화·등수 재백필 실행",
    )
    args = parser.parse_args()
    if min(
        args.days_back,
        args.max_pages,
        args.backfill_limit,
        args.max_backfill_batches,
    ) <= 0:
        parser.error("모든 숫자 옵션은 1 이상이어야 합니다")

    dates = _completed_opening_dates(args.days_back)
    before = _health()
    plan = {
        "mode": "commit" if args.commit else "dry_run",
        "days_back": args.days_back,
        "opening_dates": len(dates),
        "date_from": str(dates[0]) if dates else None,
        "date_to": str(dates[-1]) if dates else None,
        "rank_axis_before": before,
    }
    print(json.dumps(plan, ensure_ascii=False, indent=2))
    if not args.commit:
        return 0
    if not dates:
        return 0 if before.get("healthy") is True else 1

    crawl = crawl_recent_openings(
        windows=windows_for_dates(dates),
        max_pages=args.max_pages,
    )
    backfill = _backfill(args.backfill_limit, args.max_backfill_batches)
    after = _health()
    result = {
        "crawl": crawl,
        "rank_backfill": backfill,
        "rank_axis_after": after,
    }
    print(json.dumps(result, ensure_ascii=False, default=str, indent=2))

    crawl_ok = (
        bool(crawl.get("ok"))
        and bool(crawl.get("participant_ok"))
        and not crawl.get("participant_errors")
        and not crawl.get("participant_axis_rejected")
    )
    windows_ok = not crawl.get("failed_windows")
    backfill_ok = backfill["complete"]
    return 0 if (
        crawl_ok and windows_ok and backfill_ok and after.get("healthy") is True
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
