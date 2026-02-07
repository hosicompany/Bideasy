import requests
import json
from datetime import datetime, timedelta

def load_env():
    try:
        with open(".env", "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("PUBLIC_DATA_KEY="):
                    return line.split("=", 1)[1].strip()
    except:
        pass
    return None

API_KEY = load_env()
URL = "https://apis.data.go.kr/1230000/ad/BidPublicInfoService/getBidPblancListInfoCnstwk"

def test_fallback(bid_no):
    print(f"Testing Fallback API for {bid_no}...")
    
    end_date = datetime.now()
    start_date = end_date - timedelta(days=90)
    
    params = {
        "serviceKey": API_KEY,
        "numOfRows": 10,
        "pageNo": 1,
        "inqryDiv": 1,
        "inqryBgnDt": start_date.strftime("%Y%m%d0000"),
        "inqryEndDt": end_date.strftime("%Y%m%d2359"),
        "type": "json",
        "bidNtceNo": bid_no
    }
    
    try:
        resp = requests.get(URL, params=params)
        print(f"Status: {resp.status_code}")
        
        if resp.status_code != 200:
            print("Row Content:", resp.text[:200])
            return

        data = resp.json()
        items = data.get("response", {}).get("body", {}).get("items", [])
        
        if not items:
            print(" -> No items returned.")
        else:
            if isinstance(items, dict): items = [items]
            print(f" -> Found {len(items)} items.")
            print(f" -> Title: {items[0].get('bidNtceNm')}")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    # Test with the ID we know exists from previous manual crawl
    test_fallback("R25BK01253548")
