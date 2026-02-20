"""
개찰결과 고속 수집 스크립트
연도별 병렬 처리로 속도 대폭 향상

기존: 순차 1주씩 → 약 48시간
개선: 연도별 병렬 → 약 8~10시간
"""

import requests
import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

API_KEY = "fa268326385baba6b21a78ceb898d00b382b4ac3cf1d610e3c647ef3422e5905"
BASE_URL = "https://apis.data.go.kr/1230000/ao/PubDataOpnStdService/getDataSetOpnStdScsbidInfo"

DATA_DIR = Path(__file__).parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)
PROGRESS_FILE = DATA_DIR / "crawl_fast_progress.json"

# API 호출 간 최소 대기 (초) - 서버 부하 방지
MIN_DELAY = 0.2


def fetch_page(start_dt: str, end_dt: str, page: int = 1, retries: int = 3) -> list:
    params = {
        "serviceKey": API_KEY,
        "numOfRows": 100,
        "pageNo": page,
        "type": "json",
        "bsnsDivCd": "3",
        "opengBgnDt": start_dt,
        "opengEndDt": end_dt,
    }
    for attempt in range(retries):
        try:
            resp = requests.get(BASE_URL, params=params, timeout=60)
            data = resp.json()

            err = data.get("nkoneps.com.response.ResponseError", {})
            if err:
                return []

            items = data.get("response", {}).get("body", {}).get("items", [])
            if isinstance(items, dict):
                items = [items]
            return items if items else []
        except Exception:
            if attempt < retries - 1:
                time.sleep(2 * (attempt + 1))
    return []


def parse_item(item: dict) -> dict:
    def sf(val):
        try:
            return float(val) if val else 0.0
        except (ValueError, TypeError):
            return 0.0

    return {
        "bid_no": item.get("bidNtceNo", ""),
        "bid_ord": item.get("bidNtceOrd", ""),
        "title": item.get("bidNtceNm", ""),
        "org": item.get("ntceInsttNm", ""),
        "open_date": item.get("opengDate", ""),
        "basic_price": sf(item.get("bssAmt")),
        "estimated_price": sf(item.get("presmptPrce")),
        "reserved_price": sf(item.get("rsrvtnPrce")),
        "winner_company": item.get("fnlSucsfCorpNm", ""),
        "winner_price": sf(item.get("fnlSucsfAmt")),
        "winner_rate": sf(item.get("fnlSucsfRt")),
        "bid_rate": sf(item.get("bidprcRt")),
        "lower_limit_rate": sf(item.get("sucsfLwstlmtRt")),
        "bid_method": item.get("bidwinrDcsnMthdNm", ""),
        "rank": int(item.get("opengRank", 0) or 0),
        "success": item.get("sucsfYn", ""),
    }


def crawl_week(start: datetime, end: datetime) -> list:
    """1주일치 수집"""
    start_dt = start.strftime("%Y%m%d") + "0000"
    end_dt = end.strftime("%Y%m%d") + "2359"

    results = []
    page = 1

    while True:
        items = fetch_page(start_dt, end_dt, page)
        if not items:
            break

        for item in items:
            p = parse_item(item)
            if p["success"] == "Y" and p["rank"] == 1:
                results.append(p)

        if len(items) < 100:
            break

        page += 1
        time.sleep(MIN_DELAY)

        if page > 100:
            break

    return results


def crawl_year(year: int, start_date: datetime, end_date: datetime, existing_data: list) -> list:
    """1년치 수집 (주 단위 순차)"""
    # 기존 데이터 키 세트 (중복 방지)
    seen = set()
    for item in existing_data:
        seen.add(f"{item['bid_no']}-{item['bid_ord']}")

    results = list(existing_data)
    current = start_date
    week_num = 0

    while current <= end_date:
        week_end = min(current + timedelta(days=6), end_date)
        week_data = crawl_week(current, week_end)

        new_count = 0
        for item in week_data:
            key = f"{item['bid_no']}-{item['bid_ord']}"
            if key not in seen:
                seen.add(key)
                results.append(item)
                new_count += 1

        label = f"  [{year}] {current.strftime('%m/%d')}~{week_end.strftime('%m/%d')} → +{new_count}건 (총 {len(results)})"
        print(label, flush=True)

        current = week_end + timedelta(days=1)
        time.sleep(MIN_DELAY)
        week_num += 1

        # 10주마다 중간 저장
        if week_num % 10 == 0:
            save_year(year, results)

    return results


def save_year(year: int, data: list):
    out = DATA_DIR / f"opening_results_{year}.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def load_progress():
    if PROGRESS_FILE.exists():
        with open(PROGRESS_FILE) as f:
            return json.load(f)
    return {}


def save_progress(prog):
    with open(PROGRESS_FILE, "w") as f:
        json.dump(prog, f, ensure_ascii=False, indent=2)


def main():
    print("=" * 55)
    print("  개찰결과 고속 수집 (연도별 병렬)")
    print("=" * 55)

    progress = load_progress()

    # 연도별 수집 범위 설정
    year_ranges = []
    for year in range(2021, 2027):
        year_start = datetime(year, 1, 1)
        year_end = min(datetime(year, 12, 31), datetime(2026, 2, 15))

        if year_end < year_start:
            continue

        # 이미 완료된 연도 스킵
        year_status = progress.get(str(year), {})
        if year_status.get("done"):
            print(f"  [{year}] 완료됨 ({year_status.get('count', '?')}건), 스킵")
            continue

        # 중간 진행 있으면 이어서
        last = year_status.get("last_week_end", "")
        if last:
            resume_from = datetime.strptime(last, "%Y-%m-%d") + timedelta(days=1)
            if resume_from > year_end:
                continue
            year_start = resume_from

        # 기존 데이터 로드
        f = DATA_DIR / f"opening_results_{year}.json"
        existing = []
        if f.exists():
            with open(f) as fh:
                existing = json.load(fh)

        year_ranges.append((year, year_start, year_end, existing))

    if not year_ranges:
        print("\n모든 연도 수집 완료!")
        return

    print(f"\n수집 대상: {[y for y, _, _, _ in year_ranges]}")
    print(f"병렬 스레드: {min(len(year_ranges), 4)}개")
    print()

    # 연도별 병렬 수집 (최대 4개 동시)
    with ThreadPoolExecutor(max_workers=min(len(year_ranges), 4)) as executor:
        futures = {}
        for year, start, end, existing in year_ranges:
            future = executor.submit(crawl_year, year, start, end, existing)
            futures[future] = year

        for future in as_completed(futures):
            year = futures[future]
            try:
                results = future.result()
                save_year(year, results)

                # 진행 저장
                progress[str(year)] = {
                    "done": True,
                    "count": len(results),
                    "last_week_end": f"{year}-12-31",
                }
                save_progress(progress)
                print(f"\n  [{year}] 완료! {len(results)}건 저장")
            except Exception as e:
                print(f"\n  [{year}] 에러: {e}")

    # 최종 요약
    print(f"\n{'=' * 55}")
    total = 0
    for year in range(2021, 2027):
        f = DATA_DIR / f"opening_results_{year}.json"
        if f.exists():
            with open(f) as fh:
                count = len(json.load(fh))
            print(f"  {year}: {count:,}건")
            total += count
    print(f"\n  총합: {total:,}건")
    print("=" * 55)


if __name__ == "__main__":
    main()
