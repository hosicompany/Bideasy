import sys
import os
import requests
from datetime import datetime, timedelta

# Minimal script to reproduce error
url = "https://apis.data.go.kr/1230000/BidPublicInfoService04/getBidPblancListInfoCnstwk"
# Load key manually to be sure
key = ""
with open("backend/.env", "r") as f:
    for line in f:
        if line.startswith("PUBLIC_DATA_KEY="):
            key = line.strip().split("=")[1]
            break

print(f"Key: {key[:5]}...")

params = {
    "serviceKey": key,
    "numOfRows": 10,
    "pageNo": 1,
    "inqryDiv": 1,
    "inqryBgnDt": (datetime.now() - timedelta(days=30)).strftime("%Y%m%d") + "0000",
    "inqryEndDt": datetime.now().strftime("%Y%m%d") + "2359",
    "type": "json"
}

try:
    print(f"Requesting {url}...")
    # data.go.kr requires unencoded key sometimes, but requests encodes it.
    # Usually serviceKey should be passed as string if it helps, but requests params dict encodes it.
    # Let's try standard requests first.
    response = requests.get(url, params=params)
    print(f"Status Code: {response.status_code}")
    if response.status_code != 200:
        print(f"Error Body: {response.text[:500]}")
    else:
        print(f"Success Body Start: {response.text[:200]}")
        try:
            js = response.json()
            print("JSON Decode Success")
        except:
            print("JSON Decode Failed")

except Exception as e:
    print(f"Exception: {e}")
