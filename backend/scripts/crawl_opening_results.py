"""
개찰결과 대량 수집 스크립트 v3
조달청 공공데이터개방표준서비스 - getDataSetOpnStdScsbidInfo

전략: 1주일 단위로 수집 (API 범위 제한)
주의: totalCount는 전체 건수를 반환하므로 무시, 데이터가 빌 때까지 수집
"""

import requests
import json
import time
from datetime import datetime, timedelta
from pathlib import Path

API_KEY = "fa268326385baba6b21a78ceb898d00b382b4ac3cf1d610e3c647ef3422e5905"
BASE_URL = "https://apis.data.go.kr/1230000/ao/PubDataOpnStdService/getDataSetOpnStdScsbidInfo"

DATA_DIR = Path(__file__).parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)
PROGRESS_FILE = DATA_DIR / "crawl_progress.json"


def fetch_page(start_dt: str, end_dt: str, page: int = 1, retries: int = 3) -> list:
    """1페이지 조회, 파싱된 아이템 리스트 반환"""
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
                print(f" [API ERR: {err.get('header',{}).get('resultMsg','')}]", end="")
                return []

            items = data.get("response", {}).get("body", {}).get("items", [])
            if isinstance(items, dict):
                items = [items]
            return items if items else []
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(3 * (attempt + 1))
            else:
                print(f" [FAIL: {e}]", end="")
                return []
    return []


def parse_item(item: dict) -> dict:
    def sf(val):
        try: return float(val) if val else 0.0
        except: return 0.0

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


def load_progress():
    if PROGRESS_FILE.exists():
        with open(PROGRESS_FILE) as f:
            return json.load(f)
    return {}


def save_progress(prog):
    with open(PROGRESS_FILE, "w") as f:
        json.dump(prog, f, ensure_ascii=False, indent=2)


def crawl_week(start: datetime, end: datetime) -> list:
    """1주일치 낙찰 데이터 수집"""
    start_dt = start.strftime("%Y%m%d") + "0000"
    end_dt = end.strftime("%Y%m%d") + "2359"

    results = []
    page = 1
    prev_count = -1

    while True:
        items = fetch_page(start_dt, end_dt, page)

        if not items:
            break

        new_count = 0
        for item in items:
            p = parse_item(item)
            # 낙찰 건만 (rank=1, success=Y)
            if p["success"] == "Y" and p["rank"] == 1:
                results.append(p)
                new_count += 1

        # 더 이상 새 데이터 없으면 중단
        if len(items) < 100:
            break

        page += 1
        time.sleep(2)

        # 안전장치: 100페이지 넘으면 중단
        if page > 100:
            break

    return results


def main():
    print("=" * 50)
    print("개찰결과 수집 (공사, 2021~2026)")
    print(f"저장: {DATA_DIR}/")
    print("=" * 50)

    progress = load_progress()
    all_data = {}

    # 기존 연도별 파일 로드
    for year in range(2021, 2027):
        f = DATA_DIR / f"opening_results_{year}.json"
        if f.exists():
            with open(f) as fh:
                all_data[year] = json.load(fh)
            print(f"[{year}] 기존 {len(all_data[year])}건 로드")
        else:
            all_data[year] = []

    # 주 단위 수집
    start = datetime(2021, 1, 1)
    end_final = datetime(2026, 2, 15)

    # 진행상황에서 마지막 완료 주차 이후부터
    last_done = progress.get("last_week_end", "")
    # 로리가 수정한 형식 호환
    if not last_done:
        for y in sorted(progress.keys()):
            if isinstance(progress[y], dict) and "last_week_end" in progress[y]:
                last_done = progress[y]["last_week_end"]
    if last_done:
        start = datetime.strptime(last_done, "%Y-%m-%d") + timedelta(days=1)
        print(f"\n{start.strftime('%Y-%m-%d')}부터 재개")

    current = start
    week_count = 0

    while current <= end_final:
        week_end = min(current + timedelta(days=6), end_final)
        label = f"{current.strftime('%Y-%m-%d')}~{week_end.strftime('%m-%d')}"
        print(f"  {label}", end="", flush=True)

        week_data = crawl_week(current, week_end)
        print(f" → {len(week_data)}건")

        # 연도별 분류
        for item in week_data:
            year_str = item.get("open_date", "")[:4]
            if year_str:
                year = int(year_str)
                if year in all_data:
                    all_data[year].append(item)

        # 진행 저장
        progress["last_week_end"] = week_end.strftime("%Y-%m-%d")
        save_progress(progress)

        # 3주마다 중간 저장
        week_count += 1
        if week_count % 3 == 0:
            for year, items in all_data.items():
                if items:
                    out = DATA_DIR / f"opening_results_{year}.json"
                    # 중복 제거
                    seen = set()
                    unique = []
                    for it in items:
                        key = f"{it['bid_no']}-{it['bid_ord']}"
                        if key not in seen:
                            seen.add(key)
                            unique.append(it)
                    all_data[year] = unique
                    with open(out, "w", encoding="utf-8") as f:
                        json.dump(unique, f, ensure_ascii=False)
            total = sum(len(v) for v in all_data.values())
            print(f"  [중간저장] 총 {total}건")

        current = week_end + timedelta(days=1)
        time.sleep(3)

    # 최종 저장
    print(f"\n{'=' * 50}")
    total = 0
    for year in sorted(all_data.keys()):
        items = all_data[year]
        if items:
            # 중복 제거
            seen = set()
            unique = []
            for it in items:
                key = f"{it['bid_no']}-{it['bid_ord']}"
                if key not in seen:
                    seen.add(key)
                    unique.append(it)

            out = DATA_DIR / f"opening_results_{year}.json"
            with open(out, "w", encoding="utf-8") as f:
                json.dump(unique, f, ensure_ascii=False, indent=2)
            print(f"  {year}: {len(unique)}건")
            total += len(unique)

    progress["done"] = True
    progress["total"] = total
    save_progress(progress)
    print(f"\n완료! 총 {total}건")


if __name__ == "__main__":
    main()
