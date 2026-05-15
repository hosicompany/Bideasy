"""
복수예비가격 수집 스크립트
기존 4,965건의 입찰건에 대해 15개 복수예비가격 + 추첨정보 수집

API: 조달청 낙찰정보서비스
엔드포인트: getOpengResultListInfoCnstwkPreparPcDetail
"""

import os
import json
import time
import sys
import urllib.request
import urllib.parse
from pathlib import Path
from datetime import datetime

DATA_DIR = Path(__file__).parent.parent / "data"
API_KEY = os.environ.get("PUBLIC_DATA_KEY") or ""
if not API_KEY:
    raise SystemExit(
        "PUBLIC_DATA_KEY 환경 변수가 없습니다. "
        "backend/.env 에 설정하거나 export PUBLIC_DATA_KEY=... 후 재실행하세요."
    )
BASE_URL = "https://apis.data.go.kr/1230000/as/ScsbidInfoService/getOpengResultListInfoCnstwkPreparPcDetail"

PROGRESS_FILE = DATA_DIR / "prelim_price_progress.json"
OUTPUT_FILE = DATA_DIR / "preliminary_prices.json"


def load_bid_numbers():
    """기존 데이터에서 입찰번호 목록 로드"""
    bid_list = []
    for year in range(2021, 2026):
        f = DATA_DIR / f"opening_results_{year}.json"
        if f.exists():
            items = json.load(open(f))
            for item in items:
                bid_no = item.get("bid_no", "")
                bid_ord = item.get("bid_ord", "000")
                if bid_no:
                    bid_list.append((bid_no, bid_ord))
    return bid_list


def fetch_preliminary_prices(bid_no, bid_ord="000"):
    """단건 복수예비가격 조회"""
    params = {
        "serviceKey": API_KEY,
        "numOfRows": "20",
        "pageNo": "1",
        "type": "json",
        "inqryDiv": "2",
        "bidNtceNo": bid_no,
    }

    url = f"{BASE_URL}?{urllib.parse.urlencode(params)}"

    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        # 응답 파싱
        body = data.get("response", {}).get("body", {})
        total = body.get("totalCount", 0)

        if total == 0:
            return None

        items = body.get("items", [])
        if isinstance(items, dict):
            items = items.get("item", [])
        if isinstance(items, dict):
            items = [items]

        # 15개 예비가격 정리
        prices = []
        for item in items:
            prices.append({
                "seq": item.get("compnoRsrvtnPrceSno", ""),
                "price": int(item.get("bsisPlnprc", 0) or 0),
                "drawn": item.get("drwtYn", "N") == "Y",
            })

        if not prices:
            return None

        # 기초금액, 예정가격도 함께 저장
        first = items[0]
        result = {
            "bid_no": bid_no,
            "bid_ord": bid_ord,
            "title": first.get("bidNtceNm", ""),
            "basic_price": int(first.get("bssamt", 0) or 0),
            "design_price": int(first.get("plnprc", 0) or 0),
            "total_count": int(first.get("totRsrvtnPrceNum", 0) or 0),
            "preliminary_prices": sorted(prices, key=lambda x: x["seq"]),
            "drawn_count": sum(1 for p in prices if p["drawn"]),
            "open_date": first.get("rlOpengDt", ""),
        }

        return result

    except Exception as e:
        return {"bid_no": bid_no, "error": str(e)}


def load_progress():
    """진행 상황 로드"""
    if PROGRESS_FILE.exists():
        return json.load(open(PROGRESS_FILE))
    return {"completed": [], "results": [], "errors": []}


def save_progress(progress):
    """진행 상황 저장"""
    with open(PROGRESS_FILE, "w") as f:
        json.dump(progress, f, ensure_ascii=False)


def save_results(results):
    """최종 결과 저장"""
    with open(OUTPUT_FILE, "w") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)


def main():
    bid_list = load_bid_numbers()
    print(f"수집 대상: {len(bid_list)}건")

    progress = load_progress()
    completed_set = set(progress["completed"])
    results = progress["results"]
    errors = progress["errors"]

    remaining = [(bn, bo) for bn, bo in bid_list if bn not in completed_set]
    print(f"이미 수집: {len(completed_set)}건")
    print(f"남은 건수: {len(remaining)}건")
    print(f"시작: {datetime.now().strftime('%H:%M:%S')}")
    print()

    start_time = time.time()
    batch_count = 0
    time.time()

    for i, (bid_no, bid_ord) in enumerate(remaining):
        result = fetch_preliminary_prices(bid_no, bid_ord)

        if result and "error" not in result:
            results.append(result)
            completed_set.add(bid_no)
            progress["completed"].append(bid_no)
            batch_count += 1
        elif result and "error" in result:
            errors.append(result)
            completed_set.add(bid_no)
            progress["completed"].append(bid_no)
        else:
            # 데이터 없음 (복수예비가격 미적용 건)
            completed_set.add(bid_no)
            progress["completed"].append(bid_no)

        # 50건마다 저장
        if (i + 1) % 50 == 0:
            save_progress(progress)

            elapsed = time.time() - start_time
            rate = (i + 1) / elapsed if elapsed > 0 else 0
            eta_min = (len(remaining) - i - 1) / rate / 60 if rate > 0 else 0
            len(results) - len(progress.get("_prev_results", []))

            now = datetime.now().strftime("%H:%M:%S")
            print(f"  [{now}] {len(completed_set)}/{len(bid_list)} "
                  f"({len(completed_set)/len(bid_list)*100:.1f}%) | "
                  f"성공 {len(results)}건 | 에러 {len(errors)}건 | "
                  f"속도 {rate:.1f}건/초 | ETA {eta_min:.0f}분")
            sys.stdout.flush()

        # API 부하 방지: 0.3초 대기
        time.sleep(0.3)

    # 최종 저장
    save_progress(progress)
    save_results(results)

    elapsed = time.time() - start_time
    print(f"\n{'='*50}")
    print("  수집 완료!")
    print(f"  총 소요: {elapsed/60:.1f}분")
    print(f"  성공: {len(results)}건")
    print(f"  에러: {len(errors)}건")
    print(f"  데이터 없음: {len(completed_set) - len(results) - len(errors)}건")
    print(f"  저장: {OUTPUT_FILE}")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()
