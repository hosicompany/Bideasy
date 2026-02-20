import requests
import sys
import os

# Minimal standalone verification script
def verify_api_live():
    # Public Data Portal Endpoint (Construction Opening Results)
    
    # Needs API Key - Import from config or hardcode for test if needed
    # Using app imports to get settings safely
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
    try:
        from app.core.config import settings
        api_key = settings.PUBLIC_DATA_KEY
    except ImportError:
        print("Failed to import settings. Ensure PYTHONPATH is set.")
        return

    # Target Date: 2025-01-02 (Recent past where data exists)
    # Using a known working date from the previous crawl context
    start_str = "202501020000"
    end_str = "202501022359"

    params = {
        "serviceKey": api_key,
        "numOfRows": 10,
        "pageNo": 1,
        "inqryDiv": 1,
        "opengBgnDt": start_str,
        "opengEndDt": end_str,
        "type": "json"
    }

    # 1. Test Notice Endpoint (Control Group)
    notice_url = "https://apis.data.go.kr/1230000/ad/BidPublicInfoService/getBidPblancListInfoCnstwk"
    print("\n--- Test 1: Notice List (Control) ---")
    try:
        resp = requests.get(notice_url, params=params, timeout=10, verify=False)
        print(f"Notice API Status: {resp.status_code}")
    except Exception as e:
        print(f"Notice API Error: {e}")

    # 2. Test Opening Result Endpoint (Target)
    opening_url = "https://apis.data.go.kr/1230000/ad/BidPublicInfoService/getOpengResultListInfoCnstwk" 
    print("\n--- Test 2: Opening Result (Target) ---")
    try:
        response = requests.get(opening_url, params=params, timeout=10, verify=False)
        print(f"Opening Result Status Code: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            items = data.get("response", {}).get("body", {}).get("items", [])
            print(f"Items Count: {len(items)}")
            if items:
                first = items[0] if isinstance(items, list) else items
                print(f"Sample: {first.get('bidNtceNo')} - {first.get('succsbidderNm')}")
                print("✅ Opening Result Verification SUCCESS")
            else:
                print("⚠️ No items found (Check date range?)")
        else:
            print(f"❌ Opening Result FAILED: {response.text[:300]}")
    except Exception as e:
        print(f"❌ Exception: {e}")

if __name__ == "__main__":
    verify_api_live()
