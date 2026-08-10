"""기존 opening_results 의 금액 기준 정정 — presmptPrce → 기초금액.

왜 필요한가
-----------
크롤러가 `presmptPrce`(추정가격, 부가세 제외)를 `basic_price` 로 저장해 왔다.
실제 기초금액은 약 1.1 배다. 정적 개찰 파일은 기초금액 기준이라 한 컬럼에
두 기준이 섞였고, 그 결과 백테스트 무효율이 99% 로 튀었다.
경위 전체: docs/PRICE_BASE_DEFECT.md

왜 개찰 API 를 다시 안 읽나 (2026-08-03 실측)
--------------------------------------------
개찰 API(`getDataSetOpnStdScsbidInfo`)는 낙찰자만이 아니라 **참가자 전원 행**을
주기 때문에 하루 `totalCount` 가 **77,721건**이다. 45일치 재조회는 수천 페이지가
되고, `bidNtceNo` 로 좁히려 해도 **그 파라미터는 무시된다**(실측: 다른 공고가
돌아옴). 그래서 기초금액 전용 오퍼레이션을 쓴다 — 하루 150~200건이라 전 기간을
훑어도 2만 건 수준이다.

⛔ `basic_price * 1.1` 로 고치지 말 것
------------------------------------
실측 218건 중 2건은 두 값이 **같았다**(비율 1.0000). 일괄 곱셈은 그 건들을
망가뜨린다. 반드시 API 의 `bssamt` 실값으로 덮는다.

커버리지는 100% 가 아니다 (실측 80%)
-----------------------------------
기초금액 공고가 아예 없는 건이 있다(최저가낙찰제·제한적최저가에서 특히 많다).
못 고친 행은 **추정해서 채우지 않고 그대로 둔다** — `arm_backtest` 의 사정률
가드가 집계에서 제외한다. 잘못된 기초금액으로 낸 판정이 바로 이번 사고다.

실행 (운영 컨테이너)
--------------------
    python scripts/backfill_opening_basis.py --dry-run   # 규모 확인
    python scripts/backfill_opening_basis.py

멱등하다 — 이미 정정된 행은 값이 같아 갱신 대상에서 빠진다.
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
except (AttributeError, ValueError):
    pass

import requests  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.db import models  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.services.bid_data_quality import base_is_consistent  # noqa: E402

_URL = ("https://apis.data.go.kr/1230000/ad/BidPublicInfoService/"
        "getBidPblancListInfoCnstwkBsisAmount")
_PAGE = 500

# 기초금액 공개는 개찰보다 앞선다. 개찰일 최솟값에서 이만큼 더 거슬러 훑는다.
_LOOKBACK_DAYS = 45

def _f(v) -> float:
    if v in (None, ""):
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def fetch_day(day: str) -> list[dict]:
    """하루치 기초금액 공고 전량. 실패한 날짜는 건너뛴다(빈 리스트)."""
    out: list[dict] = []
    page = 1
    while True:
        try:
            r = requests.get(_URL, params={
                "serviceKey": settings.PUBLIC_DATA_KEY,
                "numOfRows": _PAGE, "pageNo": page, "type": "json", "inqryDiv": 1,
                "inqryBgnDt": f"{day}0000", "inqryEndDt": f"{day}2359",
            }, timeout=60)
            body = r.json()["response"]["body"]
        except Exception as e:  # noqa: BLE001
            print(f"  ! {day} p{page} 조회 실패: {type(e).__name__} {e}")
            return out
        items = body.get("items") or []
        if isinstance(items, dict):
            items = items.get("item") or []
        out.extend(items)
        total = int(body.get("totalCount") or 0)
        if not items or len(out) >= total:
            return out
        page += 1
        time.sleep(0.2)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="갱신 없이 규모만 출력")
    args = ap.parse_args()

    db = SessionLocal()
    rows = db.query(models.OpeningResult).filter(
        models.OpeningResult.open_date.isnot(None),
        models.OpeningResult.basic_price > 0,
    ).all()
    if not rows:
        print("대상 행 없음")
        return 0

    by_no = {r.bid_no: r for r in rows}
    open_days = sorted({r.open_date.date() for r in rows})
    start = open_days[0] - timedelta(days=_LOOKBACK_DAYS)
    end = open_days[-1]
    span = (end - start).days + 1
    print(f"대상 {len(rows)}건 · 개찰일 {open_days[0]} ~ {open_days[-1]}")
    print(f"기초금액 조회 창 {start} ~ {end} ({span}일)")

    fixed = same = skipped = 0
    seen_keys: set[str] = set()

    d = start
    scanned = 0
    while d <= end:
        items = fetch_day(d.strftime("%Y%m%d"))
        scanned += len(items)
        for it in items:
            bid_no = f"{it.get('bidNtceNo')}-{it.get('bidNtceOrd') or '000'}"
            row = by_no.get(bid_no)
            if row is None or bid_no in seen_keys:
                continue
            seen_keys.add(bid_no)
            bss = _f(it.get("bssamt"))
            if bss <= 0:
                skipped += 1
                continue
            rsv = _f(row.reserved_price)
            if rsv > 0 and not base_is_consistent(bss, rsv):
                print(f"  ! {bid_no} 정정 후에도 사정률 {rsv / bss:.4f} — 건너뜀")
                skipped += 1
                continue
            if abs(_f(row.basic_price) - bss) > 0.5:
                if not args.dry_run:
                    row.basic_price = bss
                fixed += 1
            else:
                same += 1
        if not args.dry_run:
            db.commit()
        if d.day == 1 or d == end:
            print(f"  … {d} 까지 스캔 {scanned}건 / 매칭 {len(seen_keys)}건")
        d += timedelta(days=1)

    unmatched = len(rows) - len(seen_keys)
    print(f"\n{'[DRY-RUN] ' if args.dry_run else ''}"
          f"정정 {fixed}건 · 이미 정상 {same}건 · 건너뜀 {skipped}건 "
          f"· 기초금액 공고 없음 {unmatched}건 (스캔 {scanned}건)")
    if unmatched:
        print("  ↑ 못 고친 행은 그대로 둔다 — arm_backtest 의 사정률 가드가 집계에서 뺀다.")
    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
