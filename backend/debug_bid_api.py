# -*- coding: utf-8 -*-
"""Debug the bid detail API directly"""
import requests
import os
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("PUBLIC_DATA_KEY")

# Try the API directly
url = "https://apis.data.go.kr/1230000/PubDataOpnStdService/getDataSetOpnStdBidPblancInfo"

params = {
    "serviceKey": API_KEY,
    "numOfRows": 10,
    "pageNo": 1,
    "type": "json",
    "bidNtceNo": "R25BK01250181",
}

print(f"Calling API: {url}")
print(f"Params: {params}")

response = requests.get(url, params=params, timeout=30)
print(f"Status: {response.status_code}")
print(f"Response length: {len(response.text)}")

# Show raw response
print("\n--- Raw Response (first 2000 chars) ---")
print(response.text[:2000])
