"""기존 opening_results 의 금액 기준 정정 — presmptPrce → bssAmt.

왜 필요한가
-----------
크롤러가 `presmptPrce`(추정가격, 부가세 제외)를 `basic_price` 로 저장해 왔다.
실제 기초금액은 `bssAmt` 이고 약 1.1 배다. 정적 개찰 파일은 기초금액 기준이라
한 컬럼에 두 기준이 섞였고, 그 결과 백테스트 무효율이 99% 로 튀었다.
경위 전체: docs/PRICE_BASE_DEFECT.md

⛔ `basic_price * 1.1` 로 고치지 말 것
------------------------------------
실측 218건 중 2건은 두 값이 **같았다**(비율 1.0000). 일괄 곱셈은 그 건들을
망가뜨린다. 반드시 API 를 다시 조회해 `bssAmt` 실값으로 덮는다.

실행 (운영 컨테이너)
--------------------
    python scripts/backfill_opening_basis.py --dry-run     # 먼저 이걸로 규모 확인
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

_URL = "https://apis.data.go.kr/1230000/ao/PubDataOpnStdService/getDataSetOpnStdScsbidInfo"
_BSNS_DIV_CONSTRUCTION = "3"
_PAGE = 500

# 사정률 허용 범위 — arm_backtest.BASE_RATIO_MIN/MAX 와 같은 근거.
# 정정 후에도 이 범위를 벗어나면 API 쪽 이상이므로 덮지 않고 남긴다.
_RATIO_MIN, _RATIO_MAX = 0.94, 1.06


def _f(v) -> float:
    if v in (None, ""):
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def fetch_day(day: str) -> list[dict]:
    """하루치 개찰 응답 전량. 실패는 빈 리스트(그 날짜만 건너뛴다)."""
    out: list[dict] = []
    page = 1
    while True:
        try:
            r = requests.get(_URL, params={
                "serviceKey": settings.PUBLIC_DATA_KEY,
                "numOfRows": _PAGE, "pageNo": page, "type": "json",
                "bsnsDivCd": _BSNS_DIV_CONSTRUCTION,
                "opengBgnDt": f"{day}0000", "opengEndDt": f"{day}2359",
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
        models.OpeningResult.open_date.isnot(None)
    ).all()
    if not rows:
        print("대상 행 없음")
        return 0

    by_no = {r.bid_no: r for r in rows}
    days = sorted({r.open_date.date() for r in rows})
    print(f"대상 {len(rows)}건 · 개찰일 {days[0]} ~ {days[-1]} ({len(days)}일)")

    fixed = same = skipped = notfound = 0
    llr_filled = 0

    d = days[0]
    while d <= days[-1]:
        items = fetch_day(d.strftime("%Y%m%d"))
        for it in items:
            bid_no = f"{it.get('bidNtceNo')}-{it.get('bidNtceOrd') or '000'}"
            row = by_no.get(bid_no)
            if row is None:
                continue
            bss = _f(it.get("bssAmt"))
            llr = _f(it.get("sucsfLwstlmtRt"))
            if bss <= 0:
                skipped += 1
                continue
            rsv = _f(row.reserved_price)
            if rsv > 0 and not (_RATIO_MIN <= rsv / bss <= _RATIO_MAX):
                # 정정해도 사정률이 이상하면 API 데이터 자체를 의심한다
                print(f"  ! {bid_no} 정정 후에도 사정률 {rsv / bss:.4f} — 건너뜀")
                skipped += 1
                continue
            changed = False
            if abs(_f(row.basic_price) - bss) > 0.5:
                if not args.dry_run:
                    row.basic_price = bss
                changed = True
            if llr > 0 and _f(row.lower_limit_rate) != llr:
                if not args.dry_run:
                    row.lower_limit_rate = llr
                llr_filled += 1
                changed = True
            fixed += changed
            same += not changed
        if not args.dry_run:
            db.commit()
        d += timedelta(days=1)

    notfound = len(rows) - fixed - same - skipped
    print(f"\n{'[DRY-RUN] ' if args.dry_run else ''}정정 {fixed}건 · 이미 정상 {same}건 "
          f"· 건너뜀 {skipped}건 · API 미발견 {notfound}건 (하한율 채움 {llr_filled}건)")
    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
