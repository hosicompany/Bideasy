"""공사 census 크롤 — 지정 기간 '전수'(모든 페이지) 수집 → JSONL.
표본 vs 전수(census) 비교의 ground truth.

- 하루 단위 창(≤24h, 과거일 0000~2359)
- 페이지 재시도(일시 ReadTimeout 방어) — 운영 크롤과 달리 census는 완전성이 중요
- resumable(.done), rate-limit 0.3s/page

실행(서버, 백그라운드):
  docker exec -d bideasy_app sh -c \
    'PYTHONPATH=/app CENSUS_START=2024-06-03 CENSUS_END=2024-06-03 \
     python scripts/census_construction.py >> /app/data/census.log 2>&1'
진행: docker exec bideasy_app tail -20 /app/data/census.log
"""
import json
import os
import sys
import time
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
import urllib3

urllib3.disable_warnings()

from app.core.config import settings
from app.services.opening_result_crawler import _BASE_URL, _parse_item_to_kwargs

START = os.environ.get("CENSUS_START", "2024-06-03")
END = os.environ.get("CENSUS_END", "2024-06-03")
OUT = os.environ.get("CENSUS_OUT", "/app/data/census_construction.jsonl")
DONE = OUT + ".done"
MAX_PAGES = int(os.environ.get("CENSUS_MAX_PAGES", "5000"))


def _fetch_robust(s: str, e: str, page: int, retries: int = 4):
    """(items, ok). ok=False = 재시도 후에도 실패(타임아웃/에러). 빈 정상응답은 ([], True)."""
    params = {
        "serviceKey": settings.PUBLIC_DATA_KEY, "numOfRows": 100, "pageNo": page,
        "type": "json", "bsnsDivCd": "3", "opengBgnDt": s, "opengEndDt": e,
    }
    for attempt in range(retries):
        try:
            r = requests.get(_BASE_URL, params=params, timeout=90, verify=False)
            if r.status_code != 200:
                time.sleep(1.5 * (attempt + 1)); continue
            data = r.json()
            if data.get("nkoneps.com.response.ResponseError"):
                return [], True  # API 에러(범위 등) → 정상 종료로 취급
            items = data.get("response", {}).get("body", {}).get("items", []) or []
            return ([items] if isinstance(items, dict) else items), True
        except Exception:  # noqa: BLE001  (ReadTimeout 등)
            time.sleep(1.5 * (attempt + 1))
    return [], False  # 재시도 소진


def _done_days() -> set:
    return set(open(DONE, encoding="utf-8").read().split()) if os.path.exists(DONE) else set()


def _crawl_day(day: datetime, fout) -> tuple[int, bool]:
    s, e = day.strftime("%Y%m%d0000"), day.strftime("%Y%m%d2359")
    seen: set[str] = set()
    n = 0
    complete = True
    for page in range(1, MAX_PAGES + 1):
        items, ok = _fetch_robust(s, e, page)
        if not ok:
            complete = False  # 이 페이지 유실 → 하루를 '완료'로 마크 안 함(resume 재시도)
            break
        if not items:
            break
        for it in items:
            kw = _parse_item_to_kwargs(it)
            if kw is None:
                continue
            bid = kw.get("bid_no")
            if not bid or bid in seen:
                continue
            seen.add(bid)
            rec = {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in kw.items()}
            fout.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
            n += 1
        if len(items) < 100:
            break
        time.sleep(0.3)
    return n, complete


def main() -> None:
    start = datetime.strptime(START, "%Y-%m-%d")
    end = datetime.strptime(END, "%Y-%m-%d")
    done = _done_days()
    total = 0
    t0 = time.time()
    print(f"CENSUS {START}~{END} → {OUT} (done={len(done)}일 스킵)", flush=True)
    with open(OUT, "a", encoding="utf-8") as fout:
        d = start
        while d <= end:
            day = d.strftime("%Y-%m-%d")
            if day in done:
                d += timedelta(days=1); continue
            n, complete = _crawl_day(d, fout)
            fout.flush()
            total += n
            status = "" if complete else " [불완전-resume필요]"
            if complete:
                with open(DONE, "a", encoding="utf-8") as fd:
                    fd.write(day + "\n")
            print(f"  {day}: {n}건{status} (누적 {total}, {time.time() - t0:.0f}s)", flush=True)
            d += timedelta(days=1)
    print(f"DONE {START}~{END}: 총 {total}건, {time.time() - t0:.0f}s → {OUT}", flush=True)


if __name__ == "__main__":
    main()
