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

개찰 API 는 조회 중 데이터가 바뀌면 페이지 경계가 이동해 한 번의 전체
스캔에도 서로 다른 시점의 순위가 섞일 수 있다. 크롤러는 그런 스냅샷을
거부하므로, 이 복구 도구는 다른 오류가 없고 순위 축 거부만 남은 경우에만
전체 창을 한 번 더 읽는다. 재시도 뒤에도 불안정하면 기존 정상 스냅샷을
보존한 채 실패로 끝난다.

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


def _recovery_succeeded(crawl: dict, backfill: dict, after: dict) -> bool:
    """안전한 개별 거부는 경고로 남기고 전역 복구 결과로 성공을 판정한다.

    최종 스냅샷의 순위 축이 어긋나면 크롤러는 기존 데이터를 건드리지 않고
    공고 전체를 거부한다. 이런 fail-closed 거부가 일부 있어도 확정 공고 전역
    건강도가 정상이라면 더 읽을 이유가 없고, 같은 이유로 CLI를 실패시켜서도
    안 된다. 조회·파싱·DB·백필 오류는 계속 실패로 판정한다.
    """
    crawl_ok = (
        bool(crawl.get("ok"))
        and bool(crawl.get("participant_ok"))
        and not crawl.get("participant_errors")
        and not crawl.get("failed_windows")
    )
    return bool(
        crawl_ok
        and backfill.get("complete")
        and after.get("healthy") is True
    )


def _crawl_with_axis_retries(
    windows: list[tuple[datetime, datetime]],
    max_pages: int,
    max_attempts: int,
    health_check=None,
) -> list[dict]:
    """순위 축 거부만 발생한 완전 스캔을 제한적으로 다시 읽는다.

    연결·파싱·페이지 실패까지 재시도하면 같은 구조적 고장을 긴 전체 스캔으로
    반복할 뿐이다. 반대로 ``participant_axis_rejected`` 는 API 페이지 경계가
    조회 중 이동했을 때 크롤러가 의도적으로 스냅샷을 보류한 신호다. 이미
    정상 반영된 공고는 다음 시도에서도 공고 단위 원자 교체/갱신을 거치므로,
    전체 창 재조회가 부분 상태를 만들지 않는다.
    """
    attempts = []
    health_check = health_check or _health
    for _ in range(max_attempts):
        crawl = crawl_recent_openings(windows=windows, max_pages=max_pages)
        attempts.append(crawl)
        retryable_axis_rejection = (
            bool(crawl.get("ok"))
            and bool(crawl.get("participant_ok"))
            and not crawl.get("failed_windows")
            and not crawl.get("participant_errors")
            and bool(crawl.get("participant_axis_rejected"))
        )
        # 거부 건이 남았더라도 이미 전역 축이 건강하면 더 읽지 않는다. API 는
        # 실행마다 페이지 경계가 달라질 수 있어, 불필요한 다음 전체 스캔이
        # 방금 복구한 표본 구성을 다시 나쁘게 만들 수 있다(2026-08-18 운영
        # 재현: 1차 후 0.170%/healthy → 2차 후 3.543%/unhealthy).
        if (
            not retryable_axis_rejection
            or health_check().get("healthy") is True
        ):
            break
    return attempts


def main() -> int:
    parser = argparse.ArgumentParser(
        description="모의투찰 최종 참가자 스냅샷과 가상 순위 복구",
    )
    parser.add_argument("--days-back", type=int, default=30)
    parser.add_argument("--max-pages", type=int, default=250)
    parser.add_argument("--backfill-limit", type=int, default=5000)
    parser.add_argument("--max-backfill-batches", type=int, default=20)
    parser.add_argument(
        "--max-crawl-attempts",
        type=int,
        default=2,
        help="순위 축 거부만 남았을 때 전체 창 재조회까지 포함한 최대 시도 횟수",
    )
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
        args.max_crawl_attempts,
    ) <= 0:
        parser.error("모든 숫자 옵션은 1 이상이어야 합니다")

    dates = _completed_opening_dates(args.days_back)
    before = _health()
    plan = {
        "mode": "commit" if args.commit else "dry_run",
        "days_back": args.days_back,
        "opening_dates": len(dates),
        "max_crawl_attempts": args.max_crawl_attempts,
        "date_from": str(dates[0]) if dates else None,
        "date_to": str(dates[-1]) if dates else None,
        "rank_axis_before": before,
    }
    print(json.dumps(plan, ensure_ascii=False, indent=2))
    if not args.commit:
        return 0
    if not dates:
        return 0 if before.get("healthy") is True else 1

    crawl_attempts = _crawl_with_axis_retries(
        windows=windows_for_dates(dates),
        max_pages=args.max_pages,
        max_attempts=args.max_crawl_attempts,
    )
    crawl = crawl_attempts[-1]
    backfill = _backfill(args.backfill_limit, args.max_backfill_batches)
    after = _health()
    result = {
        "crawl": crawl,
        "crawl_attempts": crawl_attempts,
        "rank_backfill": backfill,
        "rank_axis_after": after,
    }
    print(json.dumps(result, ensure_ascii=False, default=str, indent=2))

    return 0 if _recovery_succeeded(crawl, backfill, after) else 1


if __name__ == "__main__":
    raise SystemExit(main())
