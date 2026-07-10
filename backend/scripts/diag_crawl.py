"""진단: (1) 실제 운영 크롤러가 지금 도는지 (2) 원 API 응답 전문.
실행(서버): docker cp → docker exec bideasy_app python scripts/diag_crawl.py
"""
from datetime import datetime, timedelta

import requests
import urllib3

urllib3.disable_warnings()

from app.core.config import settings
from app.services.opening_result_crawler import crawl_recent_openings, _BASE_URL

print("=== 1) 실제 운영 크롤러 (days_back=1, max_pages=3) ===")
try:
    print(crawl_recent_openings(days_back=1, max_pages=3))
except Exception as e:  # noqa: BLE001
    print("crawler EXC:", type(e).__name__, e)

print("\n=== 2) 원 API 전문 (bsnsDivCd=3, 1일, 크롤러와 동일 window 방식) ===")
end = datetime.now()
start = end - timedelta(days=1)
p = {
    "serviceKey": settings.PUBLIC_DATA_KEY,
    "numOfRows": 10,
    "pageNo": 1,
    "type": "json",
    "bsnsDivCd": "3",
    "opengBgnDt": start.strftime("%Y%m%d%H%M"),
    "opengEndDt": end.strftime("%Y%m%d%H%M"),
}
r = requests.get(_BASE_URL, params=p, timeout=60, verify=False)
print("HTTP", r.status_code, "| win", p["opengBgnDt"], "~", p["opengEndDt"], "| keylen", len(settings.PUBLIC_DATA_KEY or ""))
print("BODY:", r.text[:2500])
