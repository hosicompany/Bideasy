"""bsnsDivCd probe — 용역/물품 코드 + 응답 스키마 확인 (읽기 전용, DB 미접근).

목적:
  개찰결과 개방표준 API(getDataSetOpnStdScsbidInfo)는 bsnsDivCd 로 업무를 구분한다.
  공사=3 은 확인됨(opening_result_crawler.py). 용역/물품 코드와, 응답 스키마가
  카테고리 무관 동일한지(= 기존 파서 _parse_item_to_kwargs 재사용 가능한지)를
  실제 1회 호출로 확정한다.

실행(서버, PUBLIC_DATA_KEY 필요):
  docker compose -f docker-compose.prod.yml --env-file .env.production -p infra \
    exec app python scripts/probe_bsns_div.py
  # 또는 backend/ 에서:  python scripts/probe_bsns_div.py

결과 읽는 법:
  - totalCount > 0 이고 keys 가 공사(=3)와 동일한 코드가 용역/물품이다.
  - keys 가 다르면 → 파서 분기 필요(설계에 반영).
  - api_error("필수값"/"등록되지 않은") 이면 그 코드는 이 엔드포인트에서 무효.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta

import requests

# backend/ 를 path 에 추가해 app 패키지 임포트 (cwd 무관)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.core.config import settings  # noqa: E402

BASE = "https://apis.data.go.kr/1230000/ao/PubDataOpnStdService/getDataSetOpnStdScsbidInfo"

# 조달청 나라장터 통상 업무구분코드 후보 — 경험적으로 확정
CANDIDATES = {
    "1": "물품(후보)",
    "2": "외자(후보)",
    "3": "공사(확인됨)",
    "4": "?(후보)",
    "5": "용역(후보)",
}

# 파서가 기대하는 핵심 필드 (스키마 동일성 확인용)
KEY_FIELDS = [
    "bidNtceNo", "bidNtceOrd", "opengDate", "opengTm",
    "presmptPrce", "rsrvtnPrce", "fnlSucsfAmt", "fnlSucsfRt",
    "fnlSucsfCorpNm", "sucsfYn", "bidprcAmt", "opengRank",
    "bsnsDivCd", "bsnsDivNm", "ntceInsttNm",
]


def probe(code: str, start_dt: str, end_dt: str, num_rows: int = 10) -> dict:
    params = {
        "serviceKey": settings.PUBLIC_DATA_KEY,
        "numOfRows": num_rows,
        "pageNo": 1,
        "type": "json",
        "bsnsDivCd": code,
        "opengBgnDt": start_dt,
        "opengEndDt": end_dt,
    }
    try:
        r = requests.get(BASE, params=params, timeout=60, verify=False)
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"}
    if r.status_code != 200:
        return {"error": f"HTTP {r.status_code}", "body": r.text[:200]}
    try:
        data = r.json()
    except Exception:  # noqa: BLE001
        return {"error": "non-JSON", "body": r.text[:200]}

    err = data.get("nkoneps.com.response.ResponseError", {})
    if err:
        msg = err.get("header", {}).get("resultMsg") or json.dumps(err, ensure_ascii=False)[:200]
        return {"api_error": msg}

    body = data.get("response", {}).get("body", {}) or {}
    items = body.get("items", []) or []
    if isinstance(items, dict):
        items = [items]
    sample = items[0] if items else None
    return {
        "totalCount": body.get("totalCount"),
        "returned": len(items),
        "sample_keys": sorted(sample.keys()) if sample else [],
        "sample_fields": {k: sample.get(k) for k in KEY_FIELDS} if sample else {},
    }


def main() -> None:
    if not settings.PUBLIC_DATA_KEY:
        print("!! PUBLIC_DATA_KEY 미설정 — 서버(.env.production)에서 실행하세요.")
        sys.exit(1)

    end = datetime.now()
    start = end - timedelta(days=30)  # 최근 30일 = 카테고리별 표본 확보 충분
    start_dt = start.strftime("%Y%m%d0000")
    end_dt = end.strftime("%Y%m%d2359")

    print(f"endpoint : {BASE}")
    print(f"window   : {start_dt} ~ {end_dt}\n")

    construction_keys = None
    for code, label in CANDIDATES.items():
        res = probe(code, start_dt, end_dt)
        print(f"=== bsnsDivCd={code}  ({label}) ===")
        if "error" in res:
            print(f"  ⚠️ network/HTTP: {res['error']}")
        elif "api_error" in res:
            print(f"  ⚠️ API: {res['api_error']}")
        else:
            print(f"  totalCount={res['totalCount']}  returned={res['returned']}")
            if code == "3":
                construction_keys = set(res["sample_keys"])
            same = (
                "  (schema == 공사)" if construction_keys and set(res["sample_keys"]) == construction_keys
                else "  (schema DIFFERS ← 파서 분기 필요)" if construction_keys and res["sample_keys"]
                else ""
            )
            print(f"  keys({len(res['sample_keys'])}){same}")
            print(f"  fields = {json.dumps(res['sample_fields'], ensure_ascii=False)}")
        print()

    print("판독: totalCount>0 + 'schema == 공사' 인 코드가 용역/물품이다.")
    print("      이 출력을 그대로 붙여주면 백필/검증 스크립트를 코드에 맞춰 완성한다.")


if __name__ == "__main__":
    main()
