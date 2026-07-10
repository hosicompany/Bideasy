"""진단: 과거일(2024) 쿼리의 window 크기별 응답성/totalCount."""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
import urllib3

urllib3.disable_warnings()

from app.core.config import settings

BASE = "https://apis.data.go.kr/1230000/ao/PubDataOpnStdService/getDataSetOpnStdScsbidInfo"

CASES = [
    ("2024 1시간", "202406030900", "202406031000"),
    ("2024 6시간", "202406030900", "202406031500"),
    ("2024 1일", "202406030000", "202406032359"),
]

for label, s, e in CASES:
    p = {
        "serviceKey": settings.PUBLIC_DATA_KEY,
        "numOfRows": 10, "pageNo": 1, "type": "json",
        "bsnsDivCd": "3", "opengBgnDt": s, "opengEndDt": e,
    }
    t0 = time.time()
    try:
        r = requests.get(BASE, params=p, timeout=90, verify=False)
        el = time.time() - t0
        j = r.json()
        err = j.get("nkoneps.com.response.ResponseError", {})
        body = j.get("response", {}).get("body", {}) or {}
        tc = body.get("totalCount")
        n = len(body.get("items", []) or [])
        msg = err.get("header", {}).get("resultMsg") if err else f"totalCount={tc} returned={n}"
        print(f"{label} [{s}~{e}] {el:.1f}s HTTP{r.status_code} -> {msg}", flush=True)
    except Exception as ex:  # noqa: BLE001
        print(f"{label} [{s}~{e}] {time.time()-t0:.1f}s EXC {type(ex).__name__}: {ex}", flush=True)
