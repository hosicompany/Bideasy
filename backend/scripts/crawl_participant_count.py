"""
참가업체수 수집 스크립트 v2
날짜 범위로 전체 수집 후 기존 데이터와 bid_no 매칭

API: 조달청 낙찰정보서비스
엔드포인트: getOpengResultListInfoCnstwk
"""

import json
import time
import sys
import urllib.request
import urllib.parse
from pathlib import Path
from datetime import datetime, timedelta

DATA_DIR = Path(__file__).parent.parent / "data"
API_KEY = "fa268326385baba6b21a78ceb898d00b382b4ac3cf1d610e3c647ef3422e5905"
BASE_URL = "https://apis.data.go.kr/1230000/as/ScsbidInfoService/getOpengResultListInfoCnstwk"

OUTPUT_FILE = DATA_DIR / "participant_counts.json"
PROGRESS_FILE = DATA_DIR / "participant_progress.json"


def load_existing_bid_nos():
    """기존 데이터의 bid_no 세트"""
    bid_nos = set()
    for year in range(2021, 2026):
        f = DATA_DIR / f"opening_results_{year}.json"
        if f.exists():
            items = json.load(open(f))
            for item in items:
                bid_nos.add(item.get("bid_no", ""))
    return bid_nos


def fetch_page(start_dt, end_dt, page, num_rows=100):
    """날짜 범위 + 페이지로 조회"""
    params = {
        "serviceKey": API_KEY,
        "numOfRows": str(num_rows),
        "pageNo": str(page),
        "type": "json",
        "inqryDiv": "1",
        "inqryBgnDt": start_dt,
        "inqryEndDt": end_dt,
    }

    url = f"{BASE_URL}?{urllib.parse.urlencode(params)}"

    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        body = data.get("response", {}).get("body", {})
        total = body.get("totalCount", 0)

        items = body.get("items", [])
        if isinstance(items, dict):
            items = items.get("item", [])
        if isinstance(items, dict):
            items = [items]

        return items, total

    except Exception as e:
        print(f"    에러: {e}")
        return [], 0


def load_progress():
    if PROGRESS_FILE.exists():
        return json.load(open(PROGRESS_FILE))
    return {"completed_periods": [], "all_results": {}}


def save_progress(progress):
    with open(PROGRESS_FILE, "w") as f:
        json.dump(progress, f, ensure_ascii=False)


def main():
    existing_bid_nos = load_existing_bid_nos()
    print(f"기존 데이터: {len(existing_bid_nos)}건의 bid_no")

    progress = load_progress()
    completed_periods = set(progress["completed_periods"])
    all_results = progress["all_results"]  # bid_no -> participant_count

    # 1주일 단위로 2021-01-01 ~ 2025-12-31 순회
    start = datetime(2021, 1, 1)
    end = datetime(2025, 12, 31)
    delta = timedelta(days=7)

    periods = []
    current = start
    while current < end:
        period_end = min(current + delta - timedelta(seconds=1), end)
        start_str = current.strftime("%Y%m%d0000")
        end_str = period_end.strftime("%Y%m%d2359")
        period_key = f"{start_str}-{end_str}"
        if period_key not in completed_periods:
            periods.append((start_str, end_str, period_key))
        current += delta

    print(f"남은 기간: {len(periods)}개 (전체 {len(periods) + len(completed_periods)}개)")
    print(f"이미 수집된 매칭: {len(all_results)}건")
    print(f"시작: {datetime.now().strftime('%H:%M:%S')}")
    print()

    start_time = time.time()
    api_calls = 0
    new_matches = 0

    for i, (start_dt, end_dt, period_key) in enumerate(periods):
        page = 1
        period_total = 0
        period_matched = 0

        while True:
            items, total = fetch_page(start_dt, end_dt, page)
            api_calls += 1

            if not items:
                break

            for item in items:
                bid_no = item.get("bidNtceNo", "")
                if bid_no in existing_bid_nos and bid_no not in all_results:
                    all_results[bid_no] = {
                        "participant_count": int(item.get("prtcptCnum", 0) or 0),
                        "title": item.get("bidNtceNm", ""),
                        "org": item.get("dminsttNm", ""),
                    }
                    period_matched += 1
                    new_matches += 1

            period_total += len(items)

            # 다음 페이지 필요?
            if page * 100 >= total:
                break
            page += 1
            time.sleep(0.3)

        completed_periods.add(period_key)
        progress["completed_periods"].append(period_key)
        progress["all_results"] = all_results

        # 10기간마다 저장 + 로그
        if (i + 1) % 10 == 0:
            save_progress(progress)

            elapsed = time.time() - start_time
            api_calls / elapsed if elapsed > 0 else 0
            eta_min = (len(periods) - i - 1) / ((i + 1) / elapsed * 60) if elapsed > 0 else 0

            now = datetime.now().strftime("%H:%M:%S")
            print(f"  [{now}] 기간 {i+1}/{len(periods)} | "
                  f"매칭 {len(all_results)}건 | "
                  f"API {api_calls}회 | "
                  f"ETA {eta_min:.0f}분")
            sys.stdout.flush()

        time.sleep(0.3)

    # 최종 저장
    save_progress(progress)

    # 결과를 리스트 형태로도 저장
    result_list = [{"bid_no": k, **v} for k, v in all_results.items()]
    with open(OUTPUT_FILE, "w") as f:
        json.dump(result_list, f, ensure_ascii=False, indent=2)

    elapsed = time.time() - start_time
    matched = len(all_results)
    pct = matched / len(existing_bid_nos) * 100

    print(f"\n{'='*50}")
    print("  수집 완료!")
    print(f"  총 소요: {elapsed/60:.1f}분")
    print(f"  API 호출: {api_calls}회")
    print(f"  매칭 성공: {matched}/{len(existing_bid_nos)}건 ({pct:.1f}%)")
    print(f"  저장: {OUTPUT_FILE}")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()
