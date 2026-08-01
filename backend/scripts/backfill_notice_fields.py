"""공고 필드 백필 — 매핑 교정분을 기존 행에 소급 적용 (2026-08-02).

배경: `_map_item` 이 존재하지 않는 API 키를 읽어 bid_method·contract_method·
region 이 100% 결측이었다(PR #57 에서 교정). 크롤러를 고쳐도 **이미 저장된
행은 그대로**라, 과거 날짜 범위를 다시 조회해 upsert 로 덮어써야 한다.

범위 상한이 90일인 이유: `notices.purge_old` 가 마감 90일 경과분을 매월 삭제한다.
그보다 과거를 끌어와도 다음 purge 에서 지워지므로 의미가 없다.

사용법 (서버 컨테이너 안에서):
    docker compose ... exec app python scripts/backfill_notice_fields.py --dry-run
    docker compose ... exec app python scripts/backfill_notice_fields.py
    docker compose ... exec app python scripts/backfill_notice_fields.py --category all

안전장치:
- 기본 dry-run 아님이지만, 시작 전 대상 규모와 현재 채움률을 먼저 출력한다.
- 창(window)마다 커밋 — 중간에 끊겨도 진행분은 남고, 재실행하면 이어서 채운다.
- API 호출 간 sleep — 공공데이터 포털 레이트리밋 방어.
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

# Windows 콘솔(cp949)에서 한글·em dash 출력이 깨지지 않도록 (mock_bidding_test.py 관례).
# line_buffering: 장시간 실행이라 로그를 파일로 넘기면 블록 버퍼링에 걸려
# 끝날 때까지 진행 상황이 안 보인다(`nohup ... > log` 로 돌릴 때 실제로 겪음).
try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    sys.stderr.reconfigure(encoding="utf-8", line_buffering=True)
except (AttributeError, ValueError):
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import case, func  # noqa: E402

from app.db import models  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.services.crawler import CrawlerService  # noqa: E402

CATEGORIES = ("construction", "service", "goods")
CONTRACT_TYPE = {
    "construction": "CONSTRUCTION",
    "service": "SERVICE",
    "goods": "GOODS",
}


def fill_rate(db, contract_type: str | None = None) -> dict:
    """현재 채움률 — 백필 전후 비교용."""
    q = db.query(
        func.count(models.Notice.bid_no),
        func.sum(case((func.coalesce(models.Notice.bid_method, "") != "", 1), else_=0)),
        func.sum(case((models.Notice.lower_limit_rate.isnot(None), 1), else_=0)),
        func.sum(case((func.coalesce(models.Notice.region, "") != "", 1), else_=0)),
    )
    if contract_type:
        q = q.filter(models.Notice.contract_type == contract_type)
    total, bm, llr, rg = q.one()
    total = total or 0
    return {
        "total": total,
        "bid_method": bm or 0,
        "lower_limit_rate": llr or 0,
        "region": rg or 0,
    }


def _windows(days: int, window: int):
    """오늘부터 거슬러 올라가며 [start, end] 날짜 창을 생성 (최신 우선)."""
    today = datetime.now().date()
    cursor = today
    earliest = today - timedelta(days=days)
    while cursor > earliest:
        start = max(cursor - timedelta(days=window - 1), earliest)
        yield start, cursor
        cursor = start - timedelta(days=1)


def run(days: int, categories: list[str], window: int, pages: int,
        sleep: float, dry_run: bool) -> int:
    db = SessionLocal()
    try:
        print(f"=== 공고 필드 백필 (최근 {days}일, {', '.join(categories)}) ===")
        for cat in categories:
            before = fill_rate(db, CONTRACT_TYPE[cat])
            print(f"  [{cat}] 시작 채움률: {before}")

        totals = {"fetched": 0, "inserted": 0, "updated": 0, "windows": 0}
        samples_shown = False
        for start, end in _windows(days, window):
            totals["windows"] += 1
            for cat in categories:
                for page in range(1, pages + 1):
                    items = CrawlerService.fetch_notices(
                        page=page, size=100, category=cat,
                        date_from=start.isoformat(), date_to=end.isoformat(),
                    )
                    if not items:
                        break
                    totals["fetched"] += len(items)

                    if dry_run:
                        # 첫 배치만 매핑 결과를 보여준다 (dry-run 의 목적).
                        # totals 를 올린 뒤 건수로 판정하면 영영 출력되지 않는다.
                        if not samples_shown:
                            samples_shown = True
                            for d in items[:3]:
                                print(f"    샘플: {d['bid_no']} | "
                                      f"bid_method={d.get('bid_method')!r} | "
                                      f"llr={d.get('lower_limit_rate')!r} | "
                                      f"region={d.get('region')!r} | "
                                      f"kind={d.get('notice_kind')!r}")
                    else:
                        incoming = [d["bid_no"] for d in items if d.get("bid_no")]
                        existing = {
                            row[0] for row in
                            db.query(models.Notice.bid_no)
                            .filter(models.Notice.bid_no.in_(incoming)).all()
                        } if incoming else set()
                        inserted = CrawlerService.save_notices(db, items)
                        totals["inserted"] += inserted
                        totals["updated"] += len(incoming) - len(
                            [b for b in incoming if b not in existing]
                        )
                    if sleep:
                        time.sleep(sleep)
            print(f"  {start} ~ {end} 처리 — 누적 fetched={totals['fetched']} "
                  f"inserted={totals['inserted']} updated={totals['updated']}")

        print(f"\n=== 완료: {totals} ===")
        if not dry_run:
            for cat in categories:
                after = fill_rate(db, CONTRACT_TYPE[cat])
                print(f"  [{cat}] 종료 채움률: {after}")
        return 0
    finally:
        db.close()


def main() -> int:
    p = argparse.ArgumentParser(description="공고 필드 백필 (매핑 교정 소급 적용)")
    p.add_argument("--days", type=int, default=90,
                   help="거슬러 올라갈 일수 (기본 90 — purge 경계와 일치)")
    p.add_argument("--category", default="construction",
                   choices=[*CATEGORIES, "all"],
                   help="대상 카테고리 (기본 construction)")
    p.add_argument("--window", type=int, default=7, help="조회 창 크기(일)")
    p.add_argument("--pages", type=int, default=30, help="창·카테고리당 최대 페이지")
    p.add_argument("--sleep", type=float, default=0.3, help="API 호출 간 대기(초)")
    p.add_argument("--dry-run", action="store_true",
                   help="저장하지 않고 조회·매핑 결과만 확인")
    a = p.parse_args()

    cats = list(CATEGORIES) if a.category == "all" else [a.category]
    if a.days > 90:
        print(f"⚠️  --days {a.days}: 마감 90일 경과 공고는 notices.purge_old 가 "
              f"매월 삭제하므로 90일 초과분은 곧 사라진다.")
    return run(a.days, cats, a.window, a.pages, a.sleep, a.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
